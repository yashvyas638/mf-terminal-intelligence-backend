from __future__ import annotations

from contextlib import asynccontextmanager

import json
import logging
import os
import secrets
import threading
import time
import csv
import hashlib
import base64
import binascii
import hmac
from io import StringIO
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from pathlib import Path

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select, text, tuple_
from sqlalchemy.exc import IntegrityError

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.db import (
    IngestionSnapshot,
    NavObservation,
    NavObservationRevision,
    Portfolio,
    PortfolioImportBatch,
    PortfolioTransaction,
    PortfolioTransactionAudit,
    Scheme,
    SessionLocal,
    init_db,
)
from app.analytics import performance_metrics, research_metrics
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

logger = logging.getLogger("mf_terminal.nav")

APP_VERSION = "0.3.0"
MINIMUM_VALID_RECORDS = int(os.getenv("MINIMUM_VALID_RECORDS", "1000"))
MAX_NAV_STALENESS_DAYS = int(os.getenv("MAX_NAV_STALENESS_DAYS", "7"))
_refresh_lock = threading.Lock()
NAV_REFRESH_LOCK_KEY = 0x4D46544E41565246


def _verify_trusted_database_role(db: Any) -> str:
    """Fail closed when production connects through a Supabase client role."""
    role_value = db.execute(text("SELECT current_user")).scalar_one()
    role = str(role_value or "").strip().lower()
    if not role:
        raise RuntimeError("Unable to identify the production PostgreSQL connection role")
    if role in {"anon", "authenticated"}:
        raise RuntimeError(
            "Production DATABASE_URL must use a trusted server-side PostgreSQL role; "
            "Supabase client roles are not permitted"
        )
    return role


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Production schema changes are exclusively Alembic-managed by the Render start command.
    # Local development and isolated tests retain automatic table bootstrap.
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        configured_key = os.getenv("API_KEY", "")
        if len(configured_key) < 32:
            raise RuntimeError("Production API_KEY must be configured and contain at least 32 characters")
        if MINIMUM_VALID_RECORDS < 1:
            raise RuntimeError("MINIMUM_VALID_RECORDS must be a positive integer")
        if MAX_NAV_STALENESS_DAYS < 0:
            raise RuntimeError("MAX_NAV_STALENESS_DAYS cannot be negative")
        # Fail deployment startup if the configured PostgreSQL database is unreachable.
        # Never create or mutate the production schema here; Alembic owns migrations.
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            _verify_trusted_database_role(db)
    else:
        init_db()
    yield


app = FastAPI(
    title="MF Terminal Intelligence — NAV Data Service",
    lifespan=lifespan,
    version=APP_VERSION,
    description="AMFI NAV ingestion, persistence, freshness and quality checks. Research support only; no trading.",
)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/research", include_in_schema=False)
def research_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "research.html")


def require_api_key(x_api_key: str | None) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "API_KEY is not configured; protected endpoints are disabled")
    if len(expected) < 32:
        raise HTTPException(503, "API_KEY must contain at least 32 characters; protected endpoints are disabled")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid X-API-Key")


def _read_bounded_amfi_response(response: Any, max_bytes: int = 30_000_000) -> bytes:
    """Read a streamed source body without allowing unbounded response memory."""
    headers = getattr(response, "headers", {}) or {}
    content_length = headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(502, "AMFI response exceeds the 30 MB safety limit; existing data was not changed")
        except ValueError:
            pass
    if hasattr(response, "iter_content"):
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(502, "AMFI response exceeds the 30 MB safety limit; existing data was not changed")
            chunks.append(chunk)
        return b"".join(chunks)
    payload = response.content
    if len(payload) > max_bytes:
        raise HTTPException(502, "AMFI response exceeds the 30 MB safety limit; existing data was not changed")
    return payload



def _fetch_amfi_payload(max_attempts: int = 3) -> tuple[bytes, dict[str, Any]]:
    """Fetch AMFI with bounded streaming, transient retries and source diagnostics."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = requests.get(
                AMFI_NAV_URL,
                timeout=(8, 45),
                headers={
                    "User-Agent": "MF-Terminal-Intelligence/0.4 (+NAV data service)",
                    "Accept": "text/plain, */*;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                },
                stream=True,
            )
            status = int(response.status_code)
            if status in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(f"transient AMFI HTTP status {status}", response=response)
            response.raise_for_status()
            headers = getattr(response, "headers", {}) or {}
            raw_payload = _read_bounded_amfi_response(response)
            metadata = {
                "http_status": status,
                "content_type": headers.get("Content-Type", "unknown"),
                "content_length": headers.get("Content-Length", str(len(raw_payload))),
                "bytes_received": len(raw_payload),
                "attempt": attempt,
            }
            return raw_payload, metadata
        except requests.RequestException as exc:
            last_error = exc
            retryable = not isinstance(exc, requests.HTTPError) or getattr(exc.response, "status_code", 0) in {429, 500, 502, 503, 504}
            if not retryable or attempt >= max_attempts:
                raise
            delay = min(2 ** (attempt - 1), 4)
            logger.warning("nav_source_retry attempt=%s next_delay_seconds=%s error_type=%s", attempt, delay, type(exc).__name__)
            time.sleep(delay)
        finally:
            if response is not None:
                close_response = getattr(response, "close", None)
                if callable(close_response):
                    close_response()
    raise requests.RequestException(f"AMFI request failed after retries: {type(last_error).__name__ if last_error else 'unknown'}")


def _persist_nav_snapshot(records: list[Any], report: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Persist a validated feed with batched reads and writes, preserving corrections."""
    with SessionLocal() as db:
        snapshot = IngestionSnapshot(
            source_url=AMFI_NAV_URL, retrieved_at=now, payload_sha256=report["payload_sha256"],
            records_valid=report["records_valid"], unique_scheme_codes=report["unique_scheme_codes"],
            min_nav_date=date.fromisoformat(report["min_nav_date"]),
            max_nav_date=date.fromisoformat(report["max_nav_date"]), invalid_rows=report["invalid_rows"],
            duplicate_rows_skipped=report["duplicate_rows_skipped"], quality_status=report["quality_status"],
            report_json=json.dumps(report, ensure_ascii=False),
        )
        db.add(snapshot)
        db.flush()
        codes = sorted({record.scheme_code for record in records})
        existing_schemes = {
            scheme.scheme_code: scheme
            for offset in range(0, len(codes), 500)
            for scheme in db.execute(select(Scheme).where(Scheme.scheme_code.in_(codes[offset:offset + 500]))).scalars()
        }
        keys = [(record.scheme_code, record.nav_date) for record in records]
        existing_nav = {}
        for offset in range(0, len(keys), 400):
            batch = keys[offset:offset + 400]
            rows = db.execute(
                select(NavObservation).where(tuple_(NavObservation.scheme_code, NavObservation.nav_date).in_(batch))
            ).scalars()
            for row in rows:
                existing_nav[(row.scheme_code, row.nav_date)] = row

        schemes_created = schemes_updated = 0
        nav_rows_inserted = nav_rows_updated = nav_rows_unchanged = nav_corrections_recorded = 0
        # Flush scheme master first: PostgreSQL must see FK parents before NAV rows.
        for record in records:
            scheme = existing_schemes.get(record.scheme_code)
            if scheme is None:
                scheme = Scheme(
                    scheme_code=record.scheme_code, scheme_name=record.scheme_name,
                    isin_growth=record.isin_growth, isin_dividend_reinvestment=record.isin_dividend_reinvestment,
                    first_seen_at=now, last_seen_at=now,
                    plan_type=record.plan_type, option_type=record.option_type,
                )
                db.add(scheme)
                existing_schemes[record.scheme_code] = scheme
                schemes_created += 1
            else:
                schemes_updated += 1
                scheme.scheme_name = record.scheme_name
                scheme.isin_growth = record.isin_growth or scheme.isin_growth
                scheme.isin_dividend_reinvestment = record.isin_dividend_reinvestment or scheme.isin_dividend_reinvestment
                scheme.plan_type = record.plan_type or scheme.plan_type
                scheme.option_type = record.option_type or scheme.option_type
                scheme.last_seen_at = now
        db.flush()

        for record in records:
            key = (record.scheme_code, record.nav_date)
            existing = existing_nav.get(key)
            if existing is None:
                db.add(NavObservation(
                    scheme_code=record.scheme_code, nav_date=record.nav_date,
                    nav_value=record.nav, source_snapshot_id=snapshot.id,
                ))
                nav_rows_inserted += 1
            elif Decimal(existing.nav_value) != record.nav:
                db.add(NavObservationRevision(
                    scheme_code=record.scheme_code, nav_date=record.nav_date,
                    previous_nav_value=existing.nav_value, replacement_nav_value=record.nav,
                    previous_source_snapshot_id=existing.source_snapshot_id,
                    replacement_source_snapshot_id=snapshot.id, corrected_at=now,
                ))
                existing.nav_value = record.nav
                existing.source_snapshot_id = snapshot.id
                nav_rows_updated += 1
                nav_corrections_recorded += 1
            else:
                nav_rows_unchanged += 1
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("nav_database_transaction_failed records=%s payload_sha256=%s", len(records), report["payload_sha256"])
            raise
        return {
            "snapshot": snapshot, "schemes_created": schemes_created, "schemes_updated": schemes_updated,
            "nav_rows_inserted": nav_rows_inserted, "nav_rows_updated": nav_rows_updated,
            "nav_rows_unchanged": nav_rows_unchanged, "nav_corrections_recorded": nav_corrections_recorded,
        }

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
        return {"status": "ok", "service": "mf-terminal-intelligence-backend", "version": APP_VERSION, "database": "reachable", "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from None


@app.post("/v1/nav/refresh")
def refresh_nav(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    require_api_key(x_api_key)
    started_at = datetime.now(timezone.utc)
    logger.info("nav_refresh_started source=%s", AMFI_NAV_URL)
    # Prevent duplicate work and uniqueness races within a service process. Deploy one worker;
    # distributed scheduling should invoke exactly one instance.
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(409, "A NAV refresh is already in progress")
    advisory_session = SessionLocal()
    advisory_lock_acquired = False
    try:
        if advisory_session.get_bind().dialect.name == "postgresql":
            advisory_lock_acquired = bool(
                advisory_session.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": 0x4D46544E41565246},
                ).scalar_one()
            )
            if not advisory_lock_acquired:
                raise HTTPException(409, "A NAV refresh is already running on another service instance")
        fetch_started = time.perf_counter()
        try:
            raw_payload, source_meta = _fetch_amfi_payload()
            logger.info(
                "nav_source_response status=%s content_type=%s content_length=%s bytes_received=%s attempt=%s fetch_ms=%s",
                source_meta["http_status"], source_meta["content_type"], source_meta["content_length"],
                source_meta["bytes_received"], source_meta["attempt"], int((time.perf_counter() - fetch_started) * 1000),
            )
            payload = raw_payload.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            raise HTTPException(502, "AMFI response is not valid UTF-8; existing data was not changed") from None
        except requests.RequestException as exc:
            logger.exception("nav_source_request_failed error_type=%s", type(exc).__name__)
            raise HTTPException(502, f"AMFI source request failed after bounded retries: {type(exc).__name__}; existing data was not changed") from None
        try:
            records, report = parse_amfi_nav_text(payload)
        except ValueError as exc:
            logger.warning("nav_source_validation_failed reason=%s", str(exc)[:240])
            raise HTTPException(502, f"AMFI payload validation failed: {exc}; existing data was not changed") from None
        logger.info(
            "nav_source_validated records=%s schemes=%s max_nav_date=%s invalid_rows=%s duplicates=%s quality=%s",
            report["records_valid"], report["unique_scheme_codes"], report["max_nav_date"],
            report["invalid_rows"], report["duplicate_rows_skipped"], report["quality_status"],
        )
        if report["records_valid"] < MINIMUM_VALID_RECORDS:
            logger.warning(
                "nav_source_below_minimum valid_records=%s minimum=%s",
                report["records_valid"], MINIMUM_VALID_RECORDS,
            )
            raise HTTPException(502, f"AMFI payload had only {report['records_valid']} valid rows; minimum is {MINIMUM_VALID_RECORDS}; existing data was not changed")
        latest_nav_date = date.fromisoformat(report["max_nav_date"])
        nav_age_days = (date.today() - latest_nav_date).days
        if nav_age_days > MAX_NAV_STALENESS_DAYS:
            logger.warning(
                "nav_source_stale effective_age_days=%s maximum_allowed=%s",
                nav_age_days, MAX_NAV_STALENESS_DAYS,
            )
            raise HTTPException(
                502,
                f"AMFI NAV data is stale by {nav_age_days} days; maximum allowed is {MAX_NAV_STALENESS_DAYS}; existing data was not changed",
            )

        now = datetime.now(timezone.utc)
        persist_started = time.perf_counter()
        try:
            persisted = _persist_nav_snapshot(records, report, now)
            persist_ms = int((time.perf_counter() - persist_started) * 1000)
        except Exception:
            raise HTTPException(500, "NAV snapshot persistence failed; existing accepted data was preserved where the transaction rolled back") from None
        snapshot = persisted["snapshot"]
        elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        logger.info(
            "nav_refresh_committed snapshot_id=%s schemes=%s nav_inserted=%s nav_corrected=%s nav_unchanged=%s persist_ms=%s elapsed_ms=%s",
            snapshot.id, report["unique_scheme_codes"], persisted["nav_rows_inserted"],
            persisted["nav_rows_updated"], persisted["nav_rows_unchanged"], persist_ms, elapsed_ms,
        )
        return {
            "status": "ingested", "snapshot": _snapshot_dict(snapshot),
            "scheme_rows_processed": len(records),
            "schemes_created": persisted["schemes_created"], "schemes_updated": persisted["schemes_updated"],
            "nav_rows_inserted": persisted["nav_rows_inserted"], "nav_rows_updated": persisted["nav_rows_updated"],
            "nav_rows_unchanged": persisted["nav_rows_unchanged"],
            "nav_corrections_recorded": persisted["nav_corrections_recorded"],
            "nav_rows_upserted": persisted["nav_rows_inserted"] + persisted["nav_rows_updated"],
            "validation": report,
        }

    finally:
        try:
            if advisory_lock_acquired:
                advisory_session.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": 0x4D46544E41565246},
                )
        finally:
            advisory_session.close()
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
        effective_age_days = (date.today() - snapshot.max_nav_date).days
        return {
            "status": "ok",
            "scheme_master_count": count,
            "latest_snapshot": _snapshot_dict(snapshot),
            "retrieval_age_hours": round(age_hours, 2),
            "freshness_status": "FRESH_RETRIEVAL" if age_hours <= 36 else "STALE_RETRIEVAL",
            "effective_nav_age_days": effective_age_days,
            "effective_nav_status": "FRESH_EFFECTIVE_DATE" if effective_age_days <= MAX_NAV_STALENESS_DAYS else "STALE_EFFECTIVE_DATE",
            "maximum_allowed_nav_age_days": MAX_NAV_STALENESS_DAYS,
            "note": "Retrieval freshness and NAV effective-date freshness are separate measures.",
        }


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
        return {"count": len(rows), "total_matching": total, "limit": limit, "offset": offset, "items": [{"scheme_code": scheme.scheme_code, "scheme_name": scheme.scheme_name, "isin_growth": scheme.isin_growth, "isin_dividend_reinvestment": scheme.isin_dividend_reinvestment, "plan_type": scheme.plan_type, "option_type": scheme.option_type, "category": scheme.category, "asset_class": scheme.asset_class, "latest_nav": str(nav.nav_value) if nav else None, "nav_date": nav.nav_date.isoformat() if nav else None} for scheme, nav in rows]}


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



@app.get("/v1/nav/schemes/{scheme_code}")
def scheme_detail(
    scheme_code: int,
    days: int = Query(3650, ge=30, le=3650),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Return one scheme's real metadata, latest stored NAV and dated coverage."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found in the ingested scheme master")
        latest = db.execute(
            select(NavObservation)
            .where(NavObservation.scheme_code == scheme_code)
            .order_by(desc(NavObservation.nav_date))
            .limit(1)
        ).scalar_one_or_none()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        rows = db.execute(
            select(NavObservation)
            .where(NavObservation.scheme_code == scheme_code, NavObservation.nav_date >= since)
            .order_by(NavObservation.nav_date)
        ).scalars().all()
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "isin_growth": scheme.isin_growth,
            "isin_dividend_reinvestment": scheme.isin_dividend_reinvestment,
            "amc": scheme.amc, "structure": scheme.structure, "category_group": scheme.category_group,
            "category": scheme.category, "asset_class": scheme.asset_class,
            "plan_type": scheme.plan_type, "option_type": scheme.option_type,
            "first_seen_at": scheme.first_seen_at.isoformat(),
            "last_seen_at": scheme.last_seen_at.isoformat(),
            "latest_nav": str(latest.nav_value) if latest else None,
            "latest_nav_date": latest.nav_date.isoformat() if latest else None,
            "observations_in_window": len(rows),
            "window_start": rows[0].nav_date.isoformat() if rows else None,
            "window_end": rows[-1].nav_date.isoformat() if rows else None,
            "performance": performance_metrics([(row.nav_date, float(row.nav_value)) for row in rows]),
        }


class CompareFundsRequest(BaseModel):
    scheme_codes: list[int] = Field(min_length=2, max_length=10)
    days: int = Field(default=365, ge=30, le=3650)
    risk_free_rate: float = Field(default=0.06, ge=0, le=0.25)

    @model_validator(mode="after")
    def validate_codes(self) -> "CompareFundsRequest":
        if any(code <= 0 for code in self.scheme_codes):
            raise ValueError("scheme codes must be positive integers")
        if len(set(self.scheme_codes)) != len(self.scheme_codes):
            raise ValueError("scheme codes must be unique")
        return self


@app.post("/v1/analytics/compare")
def compare_funds(
    payload: CompareFundsRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Compare 2–10 funds using their own actual stored AMFI NAV observations."""
    require_api_key(x_api_key)
    since = (datetime.now(timezone.utc) - timedelta(days=payload.days)).date()
    results = []
    with SessionLocal() as db:
        for code in payload.scheme_codes:
            scheme = db.get(Scheme, code)
            if scheme is None:
                raise HTTPException(404, f"Scheme code {code} is absent from the ingested scheme master")
            rows = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code, NavObservation.nav_date >= since)
                .order_by(NavObservation.nav_date)
            ).scalars().all()
            metrics = performance_metrics(
                [(row.nav_date, float(row.nav_value)) for row in rows],
                risk_free_rate=payload.risk_free_rate,
            )
            latest = rows[-1] if rows else None
            results.append({
                "scheme_code": code,
                "scheme_name": scheme.scheme_name,
                "observations": len(rows),
                "latest_nav": str(latest.nav_value) if latest else None,
                "latest_nav_date": latest.nav_date.isoformat() if latest else None,
                "metrics": metrics,
            })
    return {
        "days_requested": payload.days,
        "risk_free_rate_assumption": payload.risk_free_rate,
        "results": results,
        "methodology": "Each scheme is calculated from its stored AMFI NAV observations. Coverage dates can differ by scheme; benchmark TRI, distributions and category peer adjustments are not included.",
    }


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




@app.get("/v1/analytics/research/{scheme_code}")
def scheme_research(
    scheme_code: int,
    days: int = Query(3650, ge=30, le=3650),
    risk_free_rate: float = Query(0.06, ge=0, le=0.25),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Fund research profile from stored NAVs, with rolling-window diagnostics."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found in ingested scheme master")
        since = (date.today() - timedelta(days=days))
        rows = db.execute(
            select(NavObservation)
            .where(NavObservation.scheme_code == scheme_code, NavObservation.nav_date >= since)
            .order_by(NavObservation.nav_date)
        ).scalars().all()
        points = [(row.nav_date, float(row.nav_value)) for row in rows]
        metrics = research_metrics(points, risk_free_rate=risk_free_rate)
        latest = rows[-1] if rows else None
        return {
            "scheme": {
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
                "isin_growth": scheme.isin_growth,
                "isin_dividend_reinvestment": scheme.isin_dividend_reinvestment,
                "amc": scheme.amc,
                "structure": scheme.structure,
                "category_group": scheme.category_group,
                "category": scheme.category,
                "asset_class": scheme.asset_class,
                "plan_type": scheme.plan_type,
                "option_type": scheme.option_type,
            },
            "latest_nav": str(latest.nav_value) if latest else None,
            "latest_nav_date": latest.nav_date.isoformat() if latest else None,
            "coverage": {
                "observations": len(rows),
                "start_date": rows[0].nav_date.isoformat() if rows else None,
                "end_date": rows[-1].nav_date.isoformat() if rows else None,
                "requested_days": days,
            },
            "metrics": metrics,
            "data_limitations": [
                "Metrics use stored AMFI NAV observations only; AMFI feed does not provide benchmark TRI, category averages, AUM, expense ratio, holdings or fund-manager history.",
                "NAV-only returns may not represent total return where distributions are not reinvested or otherwise reflected.",
                "Alpha, beta, tracking error and information ratio are withheld until an aligned benchmark total-return series is available.",
                "No missing NAV values are interpolated; rolling windows with insufficient base-date coverage are omitted.",
            ],
            "methodology_version": "nav-research-v1",
        }


@app.get("/v1/analytics/screener")
def fund_screener(
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=160),
    asset_class: str | None = Query(default=None, max_length=40),
    plan_type: str | None = Query(default=None, max_length=20),
    option_type: str | None = Query(default=None, max_length=20),
    days: int = Query(default=1095, ge=30, le=3650),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Paginated NAV-based screener. Sort in UI only within the returned page."""
    require_api_key(x_api_key)
    since = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        query = select(Scheme)
        if q:
            term = q.strip()[:120]
            if term.isdigit():
                query = query.where(Scheme.scheme_code == int(term))
            else:
                query = query.where(Scheme.scheme_name.ilike(f"%{term}%"))
        if category:
            query = query.where(Scheme.category == category)
        if asset_class:
            query = query.where(Scheme.asset_class == asset_class)
        if plan_type:
            query = query.where(Scheme.plan_type == plan_type)
        if option_type:
            query = query.where(Scheme.option_type == option_type)
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        schemes = db.execute(query.order_by(Scheme.scheme_name).offset(offset).limit(limit)).scalars().all()
        codes = [scheme.scheme_code for scheme in schemes]
        nav_rows = db.execute(
            select(NavObservation)
            .where(NavObservation.scheme_code.in_(codes), NavObservation.nav_date >= since)
            .order_by(NavObservation.scheme_code, NavObservation.nav_date)
        ).scalars().all() if codes else []
        grouped: dict[int, list[NavObservation]] = {code: [] for code in codes}
        for row in nav_rows:
            grouped[row.scheme_code].append(row)
        items = []
        for scheme in schemes:
            rows = grouped[scheme.scheme_code]
            metrics = research_metrics([(row.nav_date, float(row.nav_value)) for row in rows])
            latest = rows[-1] if rows else None
            period = metrics.get("period_returns", {})
            items.append({
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
                "category": scheme.category,
                "asset_class": scheme.asset_class,
                "plan_type": scheme.plan_type,
                "option_type": scheme.option_type,
                "latest_nav": str(latest.nav_value) if latest else None,
                "nav_date": latest.nav_date.isoformat() if latest else None,
                "observations": len(rows),
                "return_1m": period.get("1M"),
                "return_1y": period.get("1Y"),
                "return_3y": period.get("3Y"),
                "volatility": metrics.get("annualized_volatility"),
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "sortino_ratio": metrics.get("sortino_ratio"),
                "max_drawdown": metrics.get("max_drawdown"),
                "positive_month_rate": metrics.get("positive_month_rate"),
                "rolling_1y_positive_rate": metrics.get("rolling_1y", {}).get("positive_window_rate"),
                "metrics_status": metrics.get("status"),
            })
        return {
            "count": len(items),
            "total_matching": total,
            "limit": limit,
            "offset": offset,
            "days_requested": days,
            "items": items,
            "sorting_note": "The browser sorts the current page only. Use filters and pagination; a global ranked screener requires a precomputed research snapshot.",
            "classification_coverage": {
                "category_populated": sum(bool(item["category"]) for item in items),
                "asset_class_populated": sum(bool(item["asset_class"]) for item in items),
                "plan_type_populated": sum(bool(item["plan_type"]) for item in items),
                "option_type_populated": sum(bool(item["option_type"]) for item in items),
            },
            "limitations": [
                "AMFI NAV ingestion supplies scheme name, ISIN and (in the expanded feed) plan/option labels; it does not supply reliable AMC/category/asset-class classifications.",
                "Do not interpret NAV-only return as distribution-adjusted total return.",
                "This is a research screener, not an investment recommendation or trade instruction.",
            ],
        }


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")

    @model_validator(mode="after")
    def normalize_name(self) -> "PortfolioCreate":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("portfolio name cannot be blank")
        return self


class TransactionCreate(BaseModel):
    scheme_code: int = Field(gt=0)
    transaction_type: Literal["BUY", "SELL"]
    transaction_date: date
    units: Decimal = Field(gt=0)
    nav: Decimal = Field(gt=0)
    amount: Decimal = Field(gt=0)
    charges: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_transaction_date(self) -> "TransactionCreate":
        if self.transaction_date > date.today():
            raise ValueError("transaction_date cannot be in the future")
        return self


class TransactionVoid(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def normalize_reason(self) -> "TransactionVoid":
        self.reason = self.reason.strip()
        if len(self.reason) < 3:
            raise ValueError("void reason must contain at least three non-whitespace characters")
        return self


class StatementImport(BaseModel):
    """CSV import only: client retains the original statement after upload."""

    csv_text: str = Field(min_length=1, max_length=1_000_000)
    confirmation_token: str | None = Field(default=None, max_length=512)


class AllocationTarget(BaseModel):
    scheme_code: int = Field(gt=0)
    target_percent: Decimal = Field(gt=0, le=100)


class RebalanceRequest(BaseModel):
    targets: list[AllocationTarget] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_targets(self) -> "RebalanceRequest":
        if len({target.scheme_code for target in self.targets}) != len(self.targets):
            raise ValueError("target scheme codes must be unique")
        total = sum((target.target_percent for target in self.targets), Decimal("0"))
        if total != Decimal("100"):
            raise ValueError("target percentages must sum to exactly 100")
        return self


_STATEMENT_COLUMNS = {
    "transaction_date": "transaction_date",
    "date": "transaction_date",
    "scheme_code": "scheme_code",
    "scheme": "scheme_code",
    "transaction_type": "transaction_type",
    "type": "transaction_type",
    "units": "units",
    "nav": "nav",
    "amount": "amount",
    "charges": "charges",
    "notes": "notes",
}


def _statement_transactions(csv_text: str) -> list[TransactionCreate]:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV must include a header row")
    field_map = {name: _STATEMENT_COLUMNS.get(name.strip().lower()) for name in reader.fieldnames}
    required = {"transaction_date", "scheme_code", "transaction_type", "units", "nav", "amount"}
    if not required.issubset(set(field_map.values())):
        raise HTTPException(422, "CSV requires date, scheme_code, type, units, nav, and amount columns")
    transactions: list[TransactionCreate] = []
    for row_number, row in enumerate(reader, start=2):
        if row_number > 5001:
            raise HTTPException(422, "CSV may contain at most 5,000 transaction rows")
        normalized = {target: value for source, value in row.items() if (target := field_map.get(source)) and value}
        normalized.setdefault("charges", "0")
        try:
            transaction = TransactionCreate(**normalized)
            _validate_transaction_amount(transaction)
        except (ValidationError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else "invalid transaction fields"
            raise HTTPException(422, f"CSV row {row_number}: {detail}") from None
        transactions.append(transaction)
    if not transactions:
        raise HTTPException(422, "CSV contains no transaction rows")
    return transactions


def _lock_portfolio(db: Any, portfolio_id: int) -> Portfolio:
    """Serialize ledger mutations per portfolio on PostgreSQL."""
    portfolio = db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update()
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(404, "Portfolio not found")
    return portfolio


def _issue_import_confirmation_token(portfolio_id: int, statement_sha256: str, row_count: int) -> str:
    key = os.getenv("API_KEY", "")
    expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
    payload = f"{portfolio_id}:{statement_sha256}:{row_count}:{expires_at}"
    signature = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("ascii").rstrip("=")


def _verify_import_confirmation_token(
    token: str | None, portfolio_id: int, statement_sha256: str, row_count: int
) -> bool:
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload, signature = decoded.rsplit(":", 1)
        key = os.getenv("API_KEY", "")
        expected = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            return False
        token_portfolio, token_hash, token_count, expires_at = payload.split(":")
        return (
            int(token_portfolio) == portfolio_id
            and token_hash == statement_sha256
            and int(token_count) == row_count
            and int(expires_at) >= int(datetime.now(timezone.utc).timestamp())
        )
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False


def _validate_import_batch(db: Any, portfolio_id: int, transactions: list[TransactionCreate]) -> None:
    existing = db.execute(
        select(PortfolioTransaction)
        .where(PortfolioTransaction.portfolio_id == portfolio_id, PortfolioTransaction.voided_at.is_(None))
    ).scalars().all()
    events = [
        (row.transaction_date, 0, row.id or 0, row)
        for row in existing
    ]
    for index, payload in enumerate(transactions):
        proposed = PortfolioTransaction(
            portfolio_id=portfolio_id,
            scheme_code=payload.scheme_code,
            transaction_type=payload.transaction_type,
            transaction_date=payload.transaction_date,
            units=payload.units,
            nav=payload.nav,
            amount=payload.amount,
            charges=payload.charges,
            notes=payload.notes,
            created_at=datetime.now(timezone.utc),
        )
        events.append((proposed.transaction_date, 1, index, proposed))
    events.sort(key=lambda event: (event[0], event[1], event[2]))
    balances: dict[int, Decimal] = {}
    for _, source_order, row_index, row in events:
        balance = balances.get(row.scheme_code, Decimal("0"))
        balance += row.units if row.transaction_type == "BUY" else -row.units
        if balance < 0:
            suffix = f" in import row {row_index + 2}" if source_order else ""
            raise HTTPException(
                409,
                f"Import would create a negative unit balance for scheme {row.scheme_code}{suffix}",
            )
        balances[row.scheme_code] = balance


def _canonical_statement_fingerprint(transactions: list[TransactionCreate]) -> str:
    """Fingerprint normalized transaction meaning while preserving same-day row order."""
    rows = [
        {
            "transaction_date": item.transaction_date.isoformat(),
            "scheme_code": item.scheme_code,
            "transaction_type": item.transaction_type,
            "units": format(item.units.normalize(), "f"),
            "nav": format(item.nav.normalize(), "f"),
            "amount": format(item.amount.normalize(), "f"),
            "charges": format(item.charges.normalize(), "f"),
            "notes": item.notes,
        }
        for item in transactions
    ]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _transaction_details(transaction: PortfolioTransaction) -> str:
    """Serialize ledger facts at the time of an auditable mutation."""
    return json.dumps(
        {
            "portfolio_id": transaction.portfolio_id,
            "scheme_code": transaction.scheme_code,
            "transaction_type": transaction.transaction_type,
            "transaction_date": transaction.transaction_date.isoformat(),
            "units": str(transaction.units),
            "nav": str(transaction.nav),
            "amount": str(transaction.amount),
            "charges": str(transaction.charges),
            "notes": transaction.notes,
        },
        sort_keys=True,
    )


def _validate_transaction_amount(payload: TransactionCreate) -> None:
    # AMFI transactions settle to paisa.  Rejecting a mismatch prevents a ledger
    # from silently mixing units/NAV entered for one trade with cash from another.
    expected = (payload.units * payload.nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if payload.amount != expected:
        raise HTTPException(422, f"amount must equal units × nav rounded to 2 decimals ({expected})")
    if payload.transaction_type == "SELL" and payload.charges >= payload.amount:
        raise HTTPException(422, "SELL charges must be lower than gross proceeds")


def _validate_portfolio_ledger(
    db: Any, portfolio_id: int, proposed: PortfolioTransaction | None = None
) -> None:
    """Ensure every chronological prefix has non-negative units per scheme."""
    rows = db.execute(
        select(PortfolioTransaction)
        .where(PortfolioTransaction.portfolio_id == portfolio_id, PortfolioTransaction.voided_at.is_(None))
        .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
    ).scalars().all()
    if proposed is not None:
        rows.append(proposed)
        rows.sort(key=lambda row: (row.transaction_date, row.id if row.id is not None else 2**63))
    balances: dict[int, Decimal] = {}
    for row in rows:
        balance = balances.get(row.scheme_code, Decimal("0"))
        balance += row.units if row.transaction_type == "BUY" else -row.units
        if balance < 0:
            raise HTTPException(
                409,
                f"Transaction would create a negative unit balance for scheme {row.scheme_code} on {row.transaction_date.isoformat()}",
            )
        balances[row.scheme_code] = balance


@app.post("/v1/portfolios", status_code=201)
def create_portfolio(
    payload: PortfolioCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        portfolio = Portfolio(name=payload.name.strip(), currency=payload.currency, created_at=datetime.now(timezone.utc))
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        return {"id": portfolio.id, "name": portfolio.name, "currency": portfolio.currency, "created_at": portfolio.created_at.isoformat()}


@app.get("/v1/portfolios")
def list_portfolios(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        rows = db.execute(select(Portfolio).order_by(Portfolio.created_at.desc())).scalars().all()
        return {"count": len(rows), "items": [{"id": p.id, "name": p.name, "currency": p.currency, "created_at": p.created_at.isoformat()} for p in rows]}


@app.post("/v1/portfolios/{portfolio_id}/transactions", status_code=201)
def add_portfolio_transaction(
    portfolio_id: int,
    payload: TransactionCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    _validate_transaction_amount(payload)
    with SessionLocal() as db:
        _lock_portfolio(db, portfolio_id)
        if db.get(Scheme, payload.scheme_code) is None:
            raise HTTPException(404, "Scheme code not found; ingest the AMFI scheme master first")
        transaction = PortfolioTransaction(
            portfolio_id=portfolio_id, scheme_code=payload.scheme_code,
            transaction_type=payload.transaction_type, transaction_date=payload.transaction_date,
            units=payload.units, nav=payload.nav, amount=payload.amount, charges=payload.charges,
            notes=payload.notes, created_at=datetime.now(timezone.utc),
        )
        _validate_portfolio_ledger(db, portfolio_id, transaction)
        db.add(transaction)
        db.flush()
        db.add(
            PortfolioTransactionAudit(
                transaction_id=transaction.id,
                event_type="CREATED",
                event_at=datetime.now(timezone.utc),
                details_json=_transaction_details(transaction),
            )
        )
        db.commit()
        db.refresh(transaction)
        return {"id": transaction.id, "portfolio_id": portfolio_id, "scheme_code": transaction.scheme_code,
                "transaction_type": transaction.transaction_type, "transaction_date": transaction.transaction_date.isoformat(),
                "units": str(transaction.units), "nav": str(transaction.nav), "amount": str(transaction.amount),
                "charges": str(transaction.charges)}


@app.get("/v1/portfolios/{portfolio_id}/transactions")
def list_portfolio_transactions(
    portfolio_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    with SessionLocal() as db:
        if db.get(Portfolio, portfolio_id) is None:
            raise HTTPException(404, "Portfolio not found")
        rows = db.execute(
            select(PortfolioTransaction)
            .where(PortfolioTransaction.portfolio_id == portfolio_id)
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        return {
            "count": len(rows),
            "items": [
                {
                    "id": row.id,
                    "scheme_code": row.scheme_code,
                    "transaction_type": row.transaction_type,
                    "transaction_date": row.transaction_date.isoformat(),
                    "units": str(row.units),
                    "nav": str(row.nav),
                    "amount": str(row.amount),
                    "charges": str(row.charges),
                    "notes": row.notes,
                    "voided_at": row.voided_at.isoformat() if row.voided_at else None,
                    "void_reason": row.void_reason,
                }
                for row in rows
            ],
        }


@app.post("/v1/portfolios/{portfolio_id}/transactions/import/preview")
def preview_portfolio_statement(
    portfolio_id: int,
    payload: StatementImport,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Validate and preview a CSV statement without persisting transaction rows."""
    require_api_key(x_api_key)
    transactions = _statement_transactions(payload.csv_text)
    statement_sha256 = _canonical_statement_fingerprint(transactions)
    with SessionLocal() as db:
        if db.get(Portfolio, portfolio_id) is None:
            raise HTTPException(404, "Portfolio not found")
        existing_batch = db.execute(
            select(PortfolioImportBatch).where(
                PortfolioImportBatch.portfolio_id == portfolio_id,
                PortfolioImportBatch.statement_sha256 == statement_sha256,
            )
        ).scalar_one_or_none()
        if existing_batch is not None:
            raise HTTPException(409, "This statement has already been imported into this portfolio")
        scheme_codes = {transaction.scheme_code for transaction in transactions}
        schemes = db.execute(select(Scheme).where(Scheme.scheme_code.in_(scheme_codes))).scalars().all()
        scheme_names = {scheme.scheme_code: scheme.scheme_name for scheme in schemes}
        missing_codes = sorted(scheme_codes - set(scheme_names))
        if missing_codes:
            raise HTTPException(422, f"CSV references scheme codes absent from the ingested scheme master: {missing_codes}")
        _validate_import_batch(db, portfolio_id, transactions)
        buy_amount = sum(
            (item.amount + item.charges for item in transactions if item.transaction_type == "BUY"),
            Decimal("0"),
        )
        sell_amount = sum(
            (item.amount - item.charges for item in transactions if item.transaction_type == "SELL"),
            Decimal("0"),
        )
        token = _issue_import_confirmation_token(portfolio_id, statement_sha256, len(transactions))
        return {
            "status": "PREVIEW_READY",
            "portfolio_id": portfolio_id,
            "row_count": len(transactions),
            "buy_cash_outflow": str(buy_amount.quantize(Decimal("0.01"))),
            "sell_cash_inflow": str(sell_amount.quantize(Decimal("0.01"))),
            "statement_sha256": statement_sha256,
            "confirmation_token": token,
            "token_expires_in_seconds": 600,
            "rows": [
                {
                    "row_number": index + 2,
                    "scheme_code": item.scheme_code,
                    "scheme_name": scheme_names[item.scheme_code],
                    "transaction_type": item.transaction_type,
                    "transaction_date": item.transaction_date.isoformat(),
                    "units": str(item.units),
                    "nav": str(item.nav),
                    "amount": str(item.amount),
                    "charges": str(item.charges),
                }
                for index, item in enumerate(transactions)
            ],
            "note": "Preview only. No portfolio transactions have been written. Confirm this exact normalized statement within 10 minutes to commit atomically.",
        }


@app.post("/v1/portfolios/{portfolio_id}/transactions/import", status_code=201)
def import_portfolio_statement(
    portfolio_id: int,
    payload: StatementImport,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Atomically import a documented CSV format; raw statement text is not persisted."""
    require_api_key(x_api_key)
    transactions = _statement_transactions(payload.csv_text)
    statement_sha256 = _canonical_statement_fingerprint(transactions)
    if not _verify_import_confirmation_token(
        payload.confirmation_token, portfolio_id, statement_sha256, len(transactions)
    ):
        raise HTTPException(428, "A valid, unexpired preview confirmation token is required before import")
    with SessionLocal() as db:
        _lock_portfolio(db, portfolio_id)
        existing_batch = db.execute(
            select(PortfolioImportBatch).where(
                PortfolioImportBatch.portfolio_id == portfolio_id,
                PortfolioImportBatch.statement_sha256 == statement_sha256,
            )
        ).scalar_one_or_none()
        if existing_batch is not None:
            raise HTTPException(
                409,
                {
                    "message": "This exact statement has already been imported into this portfolio.",
                    "imported_count": existing_batch.imported_count,
                    "imported_at": existing_batch.imported_at.isoformat(),
                    "statement_sha256": statement_sha256,
                },
            )
        scheme_codes = {transaction.scheme_code for transaction in transactions}
        known_codes = set(db.execute(select(Scheme.scheme_code).where(Scheme.scheme_code.in_(scheme_codes))).scalars())
        missing_codes = sorted(scheme_codes - known_codes)
        if missing_codes:
            raise HTTPException(422, f"CSV references scheme codes absent from the ingested scheme master: {missing_codes}")
        proposed = [
            PortfolioTransaction(
                portfolio_id=portfolio_id,
                scheme_code=transaction.scheme_code,
                transaction_type=transaction.transaction_type,
                transaction_date=transaction.transaction_date,
                units=transaction.units,
                nav=transaction.nav,
                amount=transaction.amount,
                charges=transaction.charges,
                notes=transaction.notes,
                created_at=datetime.now(timezone.utc),
            )
            for transaction in transactions
        ]
        # Validate each prefix so two rows in the same import cannot mask an oversell.
        for transaction in proposed:
            _validate_portfolio_ledger(db, portfolio_id, transaction)
            db.add(transaction)
            db.flush()
        imported_at = datetime.now(timezone.utc)
        db.add(
            PortfolioImportBatch(
                portfolio_id=portfolio_id,
                statement_sha256=statement_sha256,
                imported_at=imported_at,
                imported_count=len(proposed),
            )
        )
        for transaction in proposed:
            db.add(
                PortfolioTransactionAudit(
                    transaction_id=transaction.id,
                    event_type="IMPORTED",
                    event_at=imported_at,
                    details_json=json.dumps(
                        {"statement_sha256": statement_sha256, "row_count": len(proposed)}, sort_keys=True
                    ),
                )
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # A concurrent identical upload may win the unique-key race.
            raise HTTPException(409, "This exact statement was imported concurrently; no duplicate rows were added") from None
        return {
            "status": "imported",
            "imported_count": len(proposed),
            "statement_sha256": statement_sha256,
            "note": "The raw CSV is intentionally not stored; retain your original statement securely.",
        }


@app.post("/v1/portfolios/{portfolio_id}/transactions/{transaction_id}/void")
def void_portfolio_transaction(
    portfolio_id: int,
    transaction_id: int,
    payload: TransactionVoid,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Void rather than delete a transaction, preserving an auditable ledger."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        _lock_portfolio(db, portfolio_id)
        transaction = db.get(PortfolioTransaction, transaction_id)
        if transaction is None or transaction.portfolio_id != portfolio_id:
            raise HTTPException(404, "Portfolio transaction not found")
        if transaction.voided_at is not None:
            raise HTTPException(409, "Portfolio transaction is already voided")
        transaction.voided_at = datetime.now(timezone.utc)
        transaction.void_reason = payload.reason.strip()
        # A void can make a later sell invalid; reject it instead of corrupting history.
        try:
            _validate_portfolio_ledger(db, portfolio_id)
        except HTTPException:
            db.rollback()
            raise HTTPException(409, "Voiding this transaction would create a negative unit balance") from None
        db.add(
            PortfolioTransactionAudit(
                transaction_id=transaction.id,
                event_type="VOIDED",
                event_at=transaction.voided_at,
                details_json=json.dumps({"reason": transaction.void_reason}, sort_keys=True),
            )
        )
        db.commit()
        return {"id": transaction.id, "status": "voided", "voided_at": transaction.voided_at.isoformat()}


@app.get("/v1/portfolios/{portfolio_id}/transactions/{transaction_id}/audit")
def transaction_audit_history(
    portfolio_id: int,
    transaction_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Return the immutable audit history for one portfolio transaction."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        transaction = db.get(PortfolioTransaction, transaction_id)
        if transaction is None or transaction.portfolio_id != portfolio_id:
            raise HTTPException(404, "Portfolio transaction not found")
        events = db.execute(
            select(PortfolioTransactionAudit)
            .where(PortfolioTransactionAudit.transaction_id == transaction_id)
            .order_by(PortfolioTransactionAudit.event_at, PortfolioTransactionAudit.id)
        ).scalars().all()
        return {
            "transaction_id": transaction_id,
            "count": len(events),
            "items": [
                {
                    "event_type": event.event_type,
                    "event_at": event.event_at.isoformat(),
                    "details": json.loads(event.details_json),
                }
                for event in events
            ],
        }


@app.post("/v1/portfolios/{portfolio_id}/rebalance/preview")
def rebalance_preview(
    portfolio_id: int,
    payload: RebalanceRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Create a non-executable target-allocation preview from stored NAVs."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        if db.get(Portfolio, portfolio_id) is None:
            raise HTTPException(404, "Portfolio not found")
        transactions = db.execute(
            select(PortfolioTransaction)
            .where(PortfolioTransaction.portfolio_id == portfolio_id, PortfolioTransaction.voided_at.is_(None))
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        units_by_scheme: dict[int, Decimal] = {}
        for transaction in transactions:
            delta = transaction.units if transaction.transaction_type == "BUY" else -transaction.units
            units_by_scheme[transaction.scheme_code] = units_by_scheme.get(transaction.scheme_code, Decimal("0")) + delta
        active_codes = {code for code, units in units_by_scheme.items() if units > 0}
        target_by_scheme = {target.scheme_code: target.target_percent for target in payload.targets}
        all_codes = active_codes | set(target_by_scheme)
        if not all_codes:
            raise HTTPException(422, "Portfolio has no active holdings or targets")
        navs: dict[int, Decimal] = {}
        nav_dates: dict[int, date] = {}
        missing_navs: list[int] = []
        stale_navs: list[tuple[int, int]] = []
        for code in all_codes:
            latest = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code)
                .order_by(desc(NavObservation.nav_date))
                .limit(1)
            ).scalar_one_or_none()
            if latest is None:
                missing_navs.append(code)
            else:
                navs[code] = Decimal(latest.nav_value)
                nav_dates[code] = latest.nav_date
                age_days = (date.today() - latest.nav_date).days
                if age_days > MAX_NAV_STALENESS_DAYS:
                    stale_navs.append((code, age_days))
        if missing_navs:
            raise HTTPException(409, f"Cannot create a rebalance preview without NAV coverage: {sorted(missing_navs)}")
        if stale_navs:
            raise HTTPException(
                409,
                f"Cannot create a rebalance preview with stale NAVs: {stale_navs}; refresh NAV data first",
            )
        current_values = {code: units_by_scheme.get(code, Decimal("0")) * navs[code] for code in all_codes}
        portfolio_value = sum(current_values.values(), Decimal("0"))
        if portfolio_value <= 0:
            raise HTTPException(422, "Portfolio market value must be positive for rebalancing")
        recommendations = []
        for code in sorted(all_codes):
            target_value = portfolio_value * target_by_scheme.get(code, Decimal("0")) / Decimal("100")
            delta_value = target_value - current_values[code]
            recommendations.append(
                {
                    "scheme_code": code,
                    "current_value": str(current_values[code].quantize(Decimal("0.01"))),
                    "current_percent": str((current_values[code] * Decimal("100") / portfolio_value).quantize(Decimal("0.01"))),
                    "target_percent": str(target_by_scheme.get(code, Decimal("0"))),
                    "difference_value": str(delta_value.quantize(Decimal("0.01"))),
                    "estimated_units": str((abs(delta_value) / navs[code]).quantize(Decimal("0.000001"))),
                    "action": "BUY" if delta_value > Decimal("0.01") else "SELL" if delta_value < Decimal("-0.01") else "HOLD",
                    "nav_used": str(navs[code]),
                    "nav_date": nav_dates[code].isoformat(),
                    "nav_age_days": (date.today() - nav_dates[code]).days,
                }
            )
        return {
            "portfolio_id": portfolio_id,
            "portfolio_value": str(portfolio_value.quantize(Decimal("0.01"))),
            "nav_effective_date_range": {
                "oldest": min(nav_dates.values()).isoformat(),
                "newest": max(nav_dates.values()).isoformat(),
            },
            "maximum_allowed_nav_age_days": MAX_NAV_STALENESS_DAYS,
            "recommendations": recommendations,
            "limitations": [
                "Preview only; it does not place trades or account for taxes, exit loads, minimum transaction sizes, or settlement rules.",
                "Verify suitability, scheme restrictions, and current NAV availability before acting.",
            ],
        }


@app.get("/v1/portfolios/{portfolio_id}/valuation")
def portfolio_valuation(
    portfolio_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    from app.analytics import xirr

    with SessionLocal() as db:
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise HTTPException(404, "Portfolio not found")
        txns = db.execute(
            select(PortfolioTransaction)
            .where(PortfolioTransaction.portfolio_id == portfolio_id, PortfolioTransaction.voided_at.is_(None))
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        holdings: dict[int, dict[str, Any]] = {}
        cashflows_decimal: list[tuple[date, Decimal]] = []
        gross_buys = Decimal("0")
        realized_proceeds = Decimal("0")
        realized_gain_loss = Decimal("0")

        for txn in txns:
            holding = holdings.setdefault(
                txn.scheme_code,
                {"units": Decimal("0"), "cost_basis": Decimal("0"), "name": str(txn.scheme_code)},
            )
            units = Decimal(txn.units)
            amount = Decimal(txn.amount)
            charges = Decimal(txn.charges)
            if txn.transaction_type == "BUY":
                total_cost = amount + charges
                holding["units"] += units
                holding["cost_basis"] += total_cost
                gross_buys += total_cost
                cashflows_decimal.append((txn.transaction_date, -total_cost))
            else:
                if units > holding["units"]:
                    raise HTTPException(
                        409,
                        f"Sell transaction exceeds available units for scheme {txn.scheme_code}",
                    )
                average_cost = holding["cost_basis"] / holding["units"] if holding["units"] else Decimal("0")
                cost_removed = holding["cost_basis"] if units == holding["units"] else average_cost * units
                net_proceeds = amount - charges
                holding["units"] -= units
                holding["cost_basis"] = Decimal("0") if holding["units"] == 0 else holding["cost_basis"] - cost_removed
                realized_proceeds += net_proceeds
                realized_gain_loss += net_proceeds - cost_removed
                cashflows_decimal.append((txn.transaction_date, net_proceeds))

        items = []
        current_value = Decimal("0")
        remaining_cost_basis = Decimal("0")
        valuation_dates = []
        missing_nav_scheme_codes: list[int] = []
        stale_nav_scheme_codes: list[int] = []
        for code, holding in holdings.items():
            scheme = db.get(Scheme, code)
            holding["name"] = scheme.scheme_name if scheme else holding["name"]
            latest = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code)
                .order_by(desc(NavObservation.nav_date))
                .limit(1)
            ).scalar_one_or_none()
            nav_value = Decimal(latest.nav_value) if latest else None
            nav_age_days = (date.today() - latest.nav_date).days if latest else None
            if holding["units"] > 0 and nav_age_days is not None and nav_age_days > MAX_NAV_STALENESS_DAYS:
                stale_nav_scheme_codes.append(code)
            value = holding["units"] * nav_value if nav_value is not None else None
            if value is not None:
                if holding["units"] > 0:
                    current_value += value
                    valuation_dates.append(latest.nav_date)
            elif holding["units"] > 0:
                missing_nav_scheme_codes.append(code)
            remaining_cost_basis += holding["cost_basis"]
            items.append(
                {
                    "scheme_code": code,
                    "scheme_name": holding["name"],
                    "units": round(float(holding["units"]), 8),
                    "cost_basis": float(holding["cost_basis"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    "latest_nav": float(nav_value) if nav_value is not None else None,
                    "nav_date": latest.nav_date.isoformat() if latest else None,
                    "nav_age_days": nav_age_days,
                    "nav_freshness": "STALE" if nav_age_days is not None and nav_age_days > MAX_NAV_STALENESS_DAYS else "FRESH" if nav_age_days is not None else "MISSING",
                    "market_value": float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None,
                }
            )

        valuation_date = max(valuation_dates) if valuation_dates else None
        valuation_complete = not missing_nav_scheme_codes
        if valuation_complete and current_value > 0 and valuation_date and txns:
            cashflows_decimal.append((valuation_date, current_value))
        unrealized_gain_loss = current_value - remaining_cost_basis if valuation_complete else None
        total_gain_loss = realized_gain_loss + unrealized_gain_loss if unrealized_gain_loss is not None else None
        cashflows = [(flow_date, float(amount)) for flow_date, amount in cashflows_decimal]
        money = lambda value: float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "currency": portfolio.currency,
            "valuation_date": valuation_date.isoformat() if valuation_date else None,
            "oldest_nav_date": min(valuation_dates).isoformat() if valuation_dates else None,
            "newest_nav_date": max(valuation_dates).isoformat() if valuation_dates else None,
            "valuation_freshness": "NO_NAV_DATA" if not valuation_dates else "STALE" if stale_nav_scheme_codes else "FRESH",
            "holdings": items,
            "gross_buy_amount": money(gross_buys),
            "realized_proceeds": money(realized_proceeds),
            "remaining_cost_basis": money(remaining_cost_basis),
            "current_value": money(current_value),
            "realized_gain_loss": money(realized_gain_loss),
            "unrealized_gain_loss": money(unrealized_gain_loss) if unrealized_gain_loss is not None else None,
            "total_gain_loss": money(total_gain_loss) if total_gain_loss is not None else None,
            "xirr": xirr(cashflows) if valuation_complete and not stale_nav_scheme_codes else None,
            "valuation_status": "COMPLETE" if valuation_complete else "PARTIAL_MISSING_NAV",
            "missing_nav_scheme_codes": missing_nav_scheme_codes,
            "stale_nav_scheme_codes": stale_nav_scheme_codes,
            "maximum_allowed_nav_age_days": MAX_NAV_STALENESS_DAYS,
            "valuation_note": (
                "Uses latest stored AMFI NAV and average-cost accounting for sold units. "
                "Record all transactions for meaningful results. Aggregate valuation and unrealized gain/loss "
                "are withheld when an active holding has no stored NAV; XIRR is also withheld when NAV inputs are stale."
            ),
        }
