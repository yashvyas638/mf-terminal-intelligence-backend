from __future__ import annotations

from contextlib import asynccontextmanager

import json
import os
import secrets
import threading
import csv
import hashlib
from io import StringIO
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from pathlib import Path

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.db import (
    IngestionSnapshot,
    NavObservation,
    NavObservationRevision,
    Portfolio,
    PortfolioTransaction,
    PortfolioTransactionAudit,
    Scheme,
    SessionLocal,
    init_db,
)
from app.analytics import performance_metrics
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text

APP_VERSION = "0.2.0"
MINIMUM_VALID_RECORDS = int(os.getenv("MINIMUM_VALID_RECORDS", "1000"))
_refresh_lock = threading.Lock()

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Production schema changes are exclusively Alembic-managed by the Render start command.
    # Local development and isolated tests retain automatic table bootstrap.
    if os.getenv("ENVIRONMENT", "").lower() != "production":
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


def require_api_key(x_api_key: str | None) -> None:
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "API_KEY is not configured; protected endpoints are disabled")
    if len(expected) < 32:
        raise HTTPException(503, "API_KEY must contain at least 32 characters; protected endpoints are disabled")
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
        raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from None


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
            raise HTTPException(502, f"AMFI source request failed: {type(exc).__name__}; existing data was not changed") from None
        try:
            records, report = parse_amfi_nav_text(payload)
        except ValueError as exc:
            raise HTTPException(502, f"AMFI payload validation failed: {exc}; existing data was not changed") from None
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
                        scheme.scheme_name = record.scheme_name
                        # A missing marker in a later feed must not erase a previously observed ISIN.
                        scheme.isin_growth = record.isin_growth or scheme.isin_growth
                        scheme.isin_dividend_reinvestment = record.isin_dividend_reinvestment or scheme.isin_dividend_reinvestment
                        scheme.last_seen_at = now
                    existing = db.execute(select(NavObservation).where(NavObservation.scheme_code == record.scheme_code, NavObservation.nav_date == record.nav_date)).scalar_one_or_none()
                    if existing:
                        if Decimal(existing.nav_value) != record.nav:
                            db.add(
                                NavObservationRevision(
                                    scheme_code=record.scheme_code,
                                    nav_date=record.nav_date,
                                    previous_nav_value=existing.nav_value,
                                    replacement_nav_value=record.nav,
                                    previous_source_snapshot_id=existing.source_snapshot_id,
                                    replacement_source_snapshot_id=snapshot.id,
                                    corrected_at=now,
                                )
                            )
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


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")


class TransactionCreate(BaseModel):
    scheme_code: int = Field(gt=0)
    transaction_type: Literal["BUY", "SELL"]
    transaction_date: date
    units: Decimal = Field(gt=0)
    nav: Decimal = Field(gt=0)
    amount: Decimal = Field(gt=0)
    charges: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = Field(default=None, max_length=500)


class TransactionVoid(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class StatementImport(BaseModel):
    """CSV import only: client retains the original statement after upload."""

    csv_text: str = Field(min_length=1, max_length=1_000_000)


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
        rows.sort(key=lambda row: (row.transaction_date, row.id or 0))
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
        if db.get(Portfolio, portfolio_id) is None:
            raise HTTPException(404, "Portfolio not found")
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


@app.post("/v1/portfolios/{portfolio_id}/transactions/import", status_code=201)
def import_portfolio_statement(
    portfolio_id: int,
    payload: StatementImport,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Atomically import a documented CSV format; raw statement text is not persisted."""
    require_api_key(x_api_key)
    transactions = _statement_transactions(payload.csv_text)
    statement_sha256 = hashlib.sha256(payload.csv_text.encode("utf-8")).hexdigest()
    with SessionLocal() as db:
        if db.get(Portfolio, portfolio_id) is None:
            raise HTTPException(404, "Portfolio not found")
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
        db.commit()
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
        missing_navs: list[int] = []
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
        if missing_navs:
            raise HTTPException(409, f"Cannot create a rebalance preview without NAV coverage: {sorted(missing_navs)}")
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
                }
            )
        return {
            "portfolio_id": portfolio_id,
            "portfolio_value": str(portfolio_value.quantize(Decimal("0.01"))),
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
        cashflows: list[tuple[date, float]] = []
        gross_buys = 0.0
        realized_proceeds = 0.0
        realized_gain_loss = 0.0

        for txn in txns:
            holding = holdings.setdefault(
                txn.scheme_code,
                {"units": 0.0, "cost_basis": 0.0, "name": str(txn.scheme_code)},
            )
            units = float(txn.units)
            amount = float(txn.amount)
            charges = float(txn.charges)
            if txn.transaction_type == "BUY":
                total_cost = amount + charges
                holding["units"] += units
                holding["cost_basis"] += total_cost
                gross_buys += total_cost
                cashflows.append((txn.transaction_date, -total_cost))
            else:
                if units > holding["units"] + 1e-8:
                    raise HTTPException(
                        409,
                        f"Sell transaction exceeds available units for scheme {txn.scheme_code}",
                    )
                average_cost = holding["cost_basis"] / holding["units"] if holding["units"] else 0.0
                cost_removed = average_cost * units
                net_proceeds = amount - charges
                holding["units"] -= units
                holding["cost_basis"] -= cost_removed
                realized_proceeds += net_proceeds
                realized_gain_loss += net_proceeds - cost_removed
                cashflows.append((txn.transaction_date, net_proceeds))

        items = []
        current_value = 0.0
        remaining_cost_basis = 0.0
        valuation_dates = []
        missing_nav_scheme_codes: list[int] = []
        for code, holding in holdings.items():
            scheme = db.get(Scheme, code)
            holding["name"] = scheme.scheme_name if scheme else holding["name"]
            latest = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code)
                .order_by(desc(NavObservation.nav_date))
                .limit(1)
            ).scalar_one_or_none()
            nav_value = float(latest.nav_value) if latest else None
            value = holding["units"] * nav_value if nav_value is not None else None
            if value is not None:
                current_value += value
                valuation_dates.append(latest.nav_date)
            elif holding["units"] > 0:
                missing_nav_scheme_codes.append(code)
            remaining_cost_basis += holding["cost_basis"]
            items.append(
                {
                    "scheme_code": code,
                    "scheme_name": holding["name"],
                    "units": round(holding["units"], 8),
                    "cost_basis": round(holding["cost_basis"], 2),
                    "latest_nav": nav_value,
                    "nav_date": latest.nav_date.isoformat() if latest else None,
                    "market_value": round(value, 2) if value is not None else None,
                }
            )

        valuation_date = max(valuation_dates) if valuation_dates else None
        valuation_complete = not missing_nav_scheme_codes
        if valuation_complete and current_value > 0 and valuation_date and txns:
            cashflows.append((valuation_date, current_value))
        unrealized_gain_loss = current_value - remaining_cost_basis if valuation_complete else None
        total_gain_loss = realized_gain_loss + unrealized_gain_loss if unrealized_gain_loss is not None else None
        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "currency": portfolio.currency,
            "valuation_date": valuation_date.isoformat() if valuation_date else None,
            "holdings": items,
            "gross_buy_amount": round(gross_buys, 2),
            "realized_proceeds": round(realized_proceeds, 2),
            "remaining_cost_basis": round(remaining_cost_basis, 2),
            "current_value": round(current_value, 2),
            "realized_gain_loss": round(realized_gain_loss, 2),
            "unrealized_gain_loss": round(unrealized_gain_loss, 2) if unrealized_gain_loss is not None else None,
            "total_gain_loss": round(total_gain_loss, 2) if total_gain_loss is not None else None,
            "xirr": xirr(cashflows) if valuation_complete else None,
            "valuation_status": "COMPLETE" if valuation_complete else "PARTIAL_MISSING_NAV",
            "missing_nav_scheme_codes": missing_nav_scheme_codes,
            "valuation_note": (
                "Uses latest stored AMFI NAV and average-cost accounting for sold units. "
                "Record all transactions for meaningful results. Aggregate valuation, unrealized gain/loss, "
                "and XIRR are withheld when an active holding has no stored NAV."
            ),
        }