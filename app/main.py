from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, Scheme, NavObservation, IngestionSnapshot, init_db
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

APP_VERSION = "0.1.0"
app = FastAPI(title="MF Terminal Intelligence — NAV Data Service", version=APP_VERSION,
              description="AMFI NAV ingestion, persistence, freshness and quality checks. Research support only; no trading.")


@app.on_event("startup")
def startup() -> None:
    init_db()


def require_api_key(x_api_key: str | None) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="API_KEY is not configured; protected endpoints are disabled")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


def _snapshot_dict(s: IngestionSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": s.id, "source_url": s.source_url,
        "retrieved_at": s.retrieved_at.isoformat(), "payload_sha256": s.payload_sha256,
        "records_valid": s.records_valid, "unique_scheme_codes": s.unique_scheme_codes,
        "min_nav_date": s.min_nav_date.isoformat(), "max_nav_date": s.max_nav_date.isoformat(),
        "invalid_rows": s.invalid_rows, "duplicate_rows_skipped": s.duplicate_rows_skipped,
        "quality_status": s.quality_status,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    # Health endpoint intentionally reveals no secrets or portfolio data.
    try:
        with SessionLocal() as db:
            db.execute(select(func.count()).select_from(Scheme)).scalar_one()
        return {"status": "ok", "service": "mf-terminal-nav", "version": APP_VERSION,
                "database": "reachable", "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {type(exc).__name__}")


@app.post("/v1/nav/refresh")
def refresh_nav(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    try:
        response = requests.get(AMFI_NAV_URL, timeout=(10, 60), headers={"User-Agent": "MF-Terminal-Intelligence/0.1 contact: user-configured"})
        response.raise_for_status()
        payload = response.content.decode("utf-8-sig", errors="replace")
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"AMFI source request failed: {type(exc).__name__}; existing data was not changed")

    try:
        records, report = parse_amfi_nav_text(payload)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"AMFI payload validation failed: {exc}; existing data was not changed")

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        snapshot = IngestionSnapshot(
            source_url=AMFI_NAV_URL, retrieved_at=now, payload_sha256=report["payload_sha256"],
            records_valid=report["records_valid"], unique_scheme_codes=report["unique_scheme_codes"],
            min_nav_date=datetime.fromisoformat(report["min_nav_date"]).date(),
            max_nav_date=datetime.fromisoformat(report["max_nav_date"]).date(),
            invalid_rows=report["invalid_rows"], duplicate_rows_skipped=report["duplicate_rows_skipped"],
            quality_status=report["quality_status"], report_json=json.dumps(report, ensure_ascii=False))
        db.add(snapshot)
        db.flush()
        inserted_or_updated_schemes = 0
        nav_upserts = 0
        try:
            for r in records:
                scheme = db.get(Scheme, r.scheme_code)
                if scheme is None:
                    scheme = Scheme(scheme_code=r.scheme_code, scheme_name=r.scheme_name,
                                    isin_growth=r.isin_growth, isin_dividend_reinvestment=r.isin_dividend_reinvestment,
                                    first_seen_at=now, last_seen_at=now)
                    db.add(scheme)
                else:
                    scheme.scheme_name = r.scheme_name
                    scheme.isin_growth = r.isin_growth
                    scheme.isin_dividend_reinvestment = r.isin_dividend_reinvestment
                    scheme.last_seen_at = now
                inserted_or_updated_schemes += 1
                existing = db.execute(select(NavObservation).where(
                    NavObservation.scheme_code == r.scheme_code,
                    NavObservation.nav_date == r.nav_date)).scalar_one_or_none()
                if existing is None:
                    db.add(NavObservation(scheme_code=r.scheme_code, nav_date=r.nav_date,
                                          nav_value=r.nav, source_snapshot_id=snapshot.id))
                else:
                    existing.nav_value = r.nav
                    existing.source_snapshot_id = snapshot.id
                nav_upserts += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"status": "ingested", "snapshot": _snapshot_dict(snapshot),
                "scheme_rows_processed": inserted_or_updated_schemes, "nav_rows_upserted": nav_upserts,
                "validation": report,
                "warning": "Official AMFI source was parsed and stored; cross-source AMC reconciliation is not yet implemented."}


@app.get("/v1/nav/status")
def nav_status(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        snapshot = db.execute(select(IngestionSnapshot).order_by(desc(IngestionSnapshot.retrieved_at)).limit(1)).scalar_one_or_none()
        count = db.execute(select(func.count()).select_from(Scheme)).scalar_one()
        if snapshot is None:
            return {"status": "not_initialized", "scheme_master_count": count, "latest_snapshot": None}
        age_hours = (datetime.now(timezone.utc) - snapshot.retrieved_at.replace(tzinfo=timezone.utc) if snapshot.retrieved_at.tzinfo is None else datetime.now(timezone.utc) - snapshot.retrieved_at).total_seconds() / 3600
        return {"status": "ok", "scheme_master_count": count, "latest_snapshot": _snapshot_dict(snapshot),
                "retrieval_age_hours": round(age_hours, 2),
                "freshness_status": "FRESH_RETRIEVAL" if age_hours <= 36 else "STALE_RETRIEVAL",
                "note": "Retrieval freshness is not the same as NAV effective date."}


@app.get("/v1/nav/schemes")
def list_schemes(q: str | None = None, limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
                x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        query = select(Scheme)
        if q:
            if q.isdigit():
                query = query.where(Scheme.scheme_code == int(q))
            else:
                query = query.where(Scheme.scheme_name.ilike(f"%{q[:120]}%"))
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        schemes = db.execute(query.order_by(Scheme.scheme_name).offset(offset).limit(limit)).scalars().all()
        output = []
        for s in schemes:
            latest = db.execute(select(NavObservation).where(NavObservation.scheme_code == s.scheme_code).order_by(desc(NavObservation.nav_date)).limit(1)).scalar_one_or_none()
            output.append({"scheme_code": s.scheme_code, "scheme_name": s.scheme_name,
                           "isin_growth": s.isin_growth, "isin_dividend_reinvestment": s.isin_dividend_reinvestment,
                           "latest_nav": str(latest.nav_value) if latest else None,
                           "nav_date": latest.nav_date.isoformat() if latest else None})
        return {"count": len(output), "total_matching": total, "limit": limit, "offset": offset, "items": output}


@app.get("/v1/nav/history/{scheme_code}")
def nav_history(scheme_code: int, days: int = Query(default=365, ge=1, le=3650),
                x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if not scheme:
            raise HTTPException(status_code=404, detail="Scheme code not found in ingested scheme master")
        rows = db.execute(select(NavObservation).where(NavObservation.scheme_code == scheme_code,
            NavObservation.nav_date >= since).order_by(NavObservation.nav_date)).scalars().all()
        return {"scheme_code": scheme_code, "scheme_name": scheme.scheme_name, "days_requested": days,
                "count": len(rows), "items": [{"date": r.nav_date.isoformat(), "nav": str(r.nav_value)} for r in rows],
                "limitation": "AMFI daily snapshots may not provide full historical coverage until repeated ingestion is established."}


@app.get("/v1/nav/snapshot/latest")
def latest_snapshot(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        snapshot = db.execute(select(IngestionSnapshot).order_by(desc(IngestionSnapshot.retrieved_at)).limit(1)).scalar_one_or_none()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No ingestion snapshot yet; call POST /v1/nav/refresh")
        return {**_snapshot_dict(snapshot), "validation_report": json.loads(snapshot.report_json)}
