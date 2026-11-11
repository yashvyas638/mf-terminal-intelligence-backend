from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from pathlib import Path

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select

from app.db import IngestionSnapshot, NavObservation, Scheme, SessionLocal, init_db
from app.analytics import performance_metrics
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

APP_VERSION = "0.2.0"
MINIMUM_VALID_RECORDS = int(os.getenv("MINIMUM_VALID_RECORDS", "1000"))
_refresh_lock = threading.Lock()

app = FastAPI(
    title="MF Terminal Intelligence — NAV Data Service",
    version=APP_VERSION,
    description="AMFI NAV ingestion, persistence, freshness and quality checks. Research support only; no trading.",
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def require_api_key(x_api_key: str | None) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "API_KEY is not configured; protected endpoints are disabled")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid X-API-Key")


def _snapshot_dict(snapshot: IngestionSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.id,
        "source_url": snapshot.source_url,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "payload_sha256": snapshot.payload_sha256,
        "records_valid": snapshot.records_valid,
        "unique_scheme_codes": snapshot.unique_scheme_codes,
        "min_nav_date": snapshot.min_nav_date.isoformat(),
        "max_nav_date": snapshot.max_nav_date.isoformat(),
        "invalid_rows": snapshot.invalid_rows,
        "duplicate_rows_skipped": snapshot.duplicate_rows_skipped,
        "quality_status": snapshot.quality_status,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        with SessionLocal() as db:
            db.execute(select(func.count()).select_from(Scheme)).scalar_one()
        return {"status": "ok", "service": "mf-terminal-nav", "version": APP_VERSION, "database": "reachable", "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        raise HTTPException(503, f"database unavailable: {type(exc).__name__}")


@app.post("/v1/nav/refresh")
def refresh_nav(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    # Prevent duplicate work and uniqueness races within a service process. Deploy one worker;
    # distributed scheduling should invoke exactly one instance.
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "A NAV refresh is already in progress")
    try:
        try:
            response = requests.get(AMFI_NAV_URL, timeout=(10, 60), headers={"User-Agent": "MF-Terminal-Intelligence/0.2"})
            response.raise_for_status()
            payload = response.content.decode("utf-8-sig", errors="replace")
        except requests.RequestException as exc:
            raise HTTPException(502, f"AMFI source request failed: {type(exc).__name__}; existing data was not changed")
        try:
            records, report = parse_amfi_nav_text(payload)
        except ValueError as exc:
            raise HTTPException(502, f"AMFI payload validation failed: {exc}; existing data was not changed")
        if report["records_valid"] < MINIMUM_VALID_RECORDS:
            raise HTTPException(502, f"AMFI payload had only {report['records_valid']} valid rows; minimum is {MINIMUM_VALID_RECORDS}; existing data was not changed")

        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            snapshot = IngestionSnapshot(source_url=AMFI_NAV_URL, retrieved_at=now, payload_sha256=report["payload_sha256"], records_valid=report["records_valid"], unique_scheme_codes=report["unique_scheme_codes"], min_nav_date=datetime.fromisoformat(report["min_nav_date"]).date(), max_nav_date=datetime.fromisoformat(report["max_nav_date"]).date(), invalid_rows=report["invalid_rows"], duplicate_rows_skipped=report["duplicate_rows_skipped"], quality_status=report["quality_status"], report_json=json.dumps(report, ensure_ascii=False))
            db.add(snapshot)
            db.flush()
            try:
                for record in records:
                    scheme = db.get(Scheme, record.scheme_code)
                    if scheme is None:
                        db.add(Scheme(scheme_code=record.scheme_code, scheme_name=record.scheme_name, isin_growth=record.isin_growth, isin_dividend_reinvestment=record.isin_dividend_reinvestment, first_seen_at=now, last_seen_at=now))
                    else:
                        scheme.scheme_name, scheme.isin_growth, scheme.isin_dividend_reinvestment, scheme.last_seen_at = record.scheme_name, record.isin_growth, record.isin_dividend_reinvestment, now
                    existing = db.execute(select(NavObservation).where(NavObservation.scheme_code == record.scheme_code, NavObservation.nav_date == record.nav_date)).scalar_one_or_none()
                    if existing:
                        existing.nav_value, existing.source_snapshot_id = record.nav, snapshot.id
                    else:
                        db.add(NavObservation(scheme_code=record.scheme_code, nav_date=record.nav_date, nav_value=record.nav, source_snapshot_id=snapshot.id))
                db.commit()
            except Exception:
                db.rollback()
                raise
            return {"status": "ingested", "snapshot": _snapshot_dict(snapshot), "scheme_rows_processed": len(records), "nav_rows_upserted": len(records), "validation": report}
    finally:
        _refresh_lock.release()


@app.get("/v1/nav/status")
def nav_status(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        snapshot = db.execute(select(IngestionSnapshot).order_by(desc(IngestionSnapshot.retrieved_at)).limit(1)).scalar_one_or_none()
        count = db.execute(select(func.count()).select_from(Scheme)).scalar_one()
        if snapshot is None:
            return {"status": "not_initialized", "scheme_master_count": count, "latest_snapshot": None}
        retrieved_at = snapshot.retrieved_at.replace(tzinfo=timezone.utc) if snapshot.retrieved_at.tzinfo is None else snapshot.retrieved_at
        age_hours = (datetime.now(timezone.utc) - retrieved_at).total_seconds() / 3600
        return {"status": "ok", "scheme_master_count": count, "latest_snapshot": _snapshot_dict(snapshot), "retrieval_age_hours": round(age_hours, 2), "freshness_status": "FRESH_RETRIEVAL" if age_hours <= 36 else "STALE_RETRIEVAL", "note": "Retrieval freshness is not the same as NAV effective date."}


@app.get("/v1/nav/schemes")
def list_schemes(q: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        query = select(Scheme)
        if q:
            query = query.where(Scheme.scheme_code == int(q) if q.isdigit() else Scheme.scheme_name.ilike(f"%{q[:120]}%"))
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        latest_id = select(NavObservation.id).where(NavObservation.scheme_code == Scheme.scheme_code).order_by(desc(NavObservation.nav_date), desc(NavObservation.id)).limit(1).correlate(Scheme).scalar_subquery()
        rows = db.execute(query.outerjoin(NavObservation, NavObservation.id == latest_id).add_columns(NavObservation).order_by(Scheme.scheme_name).offset(offset).limit(limit)).all()
        return {"count": len(rows), "total_matching": total, "limit": limit, "offset": offset, "items": [{"scheme_code": scheme.scheme_code, "scheme_name": scheme.scheme_name, "isin_growth": scheme.isin_growth, "isin_dividend_reinvestment": scheme.isin_dividend_reinvestment, "latest_nav": str(nav.nav_value) if nav else None, "nav_date": nav.nav_date.isoformat() if nav else None} for scheme, nav in rows]}


@app.get("/v1/nav/history/{scheme_code}")
def nav_history(scheme_code: int, days: int = Query(365, ge=1, le=3650), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if not scheme:
            raise HTTPException(404, "Scheme code not found in ingested scheme master")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        rows = db.execute(select(NavObservation).where(NavObservation.scheme_code == scheme_code, NavObservation.nav_date >= since).order_by(NavObservation.nav_date)).scalars().all()
        return {"scheme_code": scheme_code, "scheme_name": scheme.scheme_name, "days_requested": days, "count": len(rows), "items": [{"date": row.nav_date.isoformat(), "nav": str(row.nav_value)} for row in rows], "limitation": "AMFI daily snapshots may not provide full historical coverage until repeated ingestion is established."}


@app.get("/v1/nav/snapshot/latest")
def latest_snapshot(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        snapshot = db.execute(select(IngestionSnapshot).order_by(desc(IngestionSnapshot.retrieved_at)).limit(1)).scalar_one_or_none()
        if snapshot is None:
            raise HTTPException(404, "No ingestion snapshot yet; call POST /v1/nav/refresh")
        return {**_snapshot_dict(snapshot), "validation_report": json.loads(snapshot.report_json)}



@app.get("/v1/analytics/performance/{scheme_code}")
def scheme_performance(
    scheme_code: int,
    days: int = Query(3650, ge=30, le=3650),
    risk_free_rate: float = Query(0.06, ge=0, le=0.25),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Calculate transparent NAV-derived return and risk statistics."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found in ingested scheme master")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        rows = db.execute(
            select(NavObservation)
            .where(NavObservation.scheme_code == scheme_code, NavObservation.nav_date >= since)
            .order_by(NavObservation.nav_date)
        ).scalars().all()
        points = [(row.nav_date, float(row.nav_value)) for row in rows]
        metrics = performance_metrics(points, risk_free_rate=risk_free_rate)
        return {
            "scheme_code": scheme_code,
            "scheme_name": scheme.scheme_name,
            "days_requested": days,
            "metrics": metrics,
            "methodology": {
                "source": "Stored AMFI NAV observations",
                "annualization": "252 observations per year for volatility and ratios; calendar days for CAGR",
                "risk_free_rate": risk_free_rate,
                "limitations": [
                    "NAV total-return interpretation depends on the selected scheme NAV series and distributions.",
                    "No benchmark comparison is included in this endpoint.",
                    "Ratios are estimates and are sensitive to observation frequency and data gaps.",
                ],
            },
        }
