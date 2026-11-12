from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from contextvars import ContextVar

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
from fastapi.responses import Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, desc, func, or_, select, text, tuple_
from sqlalchemy.exc import IntegrityError

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.db import (
    BenchmarkIndex,
    BenchmarkObservation,
    BenchmarkObservationRevision,
    FundHolding,
    FundHoldingDisclosure,
    FundResearchSnapshot,
    FundWatchlistItem,
    IngestionSnapshot,
    NavObservation,
    NavObservationRevision,
    Portfolio,
    PortfolioImportBatch,
    PortfolioGoal,
    PortfolioReportSnapshot,
    PortfolioTransaction,
    PortfolioTransactionAudit,
    Scheme,
    SchemeBenchmarkAssignment,
    SessionLocal,
    init_db,
)
from app.analytics import benchmark_comparison_metrics, fifo_capital_gains, performance_metrics, portfolio_risk_metrics, project_financial_goal, research_metrics
from app.benchmark_ingest import NIFTY_HISTORICAL_DATA_URL, parse_nifty_tri_csv
from app.holdings_ingest import parse_fund_holdings_csv
from app.holdings_risk import security_concentration_metrics
from app.reporting import build_portfolio_report_pdf
from app.nav_ingest import AMFI_NAV_URL, parse_amfi_nav_text
from app.nav_history_backfill import (
    create_history_backfill_plan,
    create_storage_optimized_history_plan,
    run_history_backfill_batch,
    history_backfill_status,
)
from app.scheme_metadata import refresh_scheme_metadata
from app.fund_taxonomy import (
    canonical_asset_class,
    canonical_group,
    canonical_subcategory,
    scheme_group_filter_values,
    subcategory_filter_values,
)

logger = logging.getLogger("mf_terminal.nav")

APP_VERSION = "0.3.0"
MINIMUM_VALID_RECORDS = int(os.getenv("MINIMUM_VALID_RECORDS", "1000"))
MAX_NAV_STALENESS_DAYS = int(os.getenv("MAX_NAV_STALENESS_DAYS", "7"))
_refresh_lock = threading.Lock()
_research_snapshot_refresh_lock = threading.Lock()
NAV_REFRESH_LOCK_KEY = 0x4D46544E41565246


def _maybe_plan_historical_backfill_from_environment() -> dict[str, Any] | None:
    """Create idempotent history checkpoints only when an operator opts in via deploy env."""
    plan_enabled = os.getenv("AMFI_HISTORY_PLAN_ON_START", "").strip().lower() == "true"
    if not plan_enabled:
        logger.warning(
            "amfi_history_backfill_plan_skipped",
            extra={
                "plan_on_start_enabled": False,
                "source_contract_verified": os.getenv(
                    "AMFI_HISTORY_CONTRACT_VERIFIED", ""
                ).strip().lower() == "true",
            },
        )
        return None
    if os.getenv("AMFI_HISTORY_CONTRACT_VERIFIED", "").strip().lower() != "true":
        raise RuntimeError(
            "Historical backfill planning requires AMFI_HISTORY_CONTRACT_VERIFIED=true"
        )

    start_raw = os.getenv("AMFI_HISTORY_BACKFILL_START_DATE", "").strip()
    end_raw = os.getenv("AMFI_HISTORY_BACKFILL_END_DATE", "").strip()
    if not start_raw or not end_raw:
        raise RuntimeError(
            "Historical backfill planning requires AMFI_HISTORY_BACKFILL_START_DATE "
            "and AMFI_HISTORY_BACKFILL_END_DATE"
        )
    try:
        start_date = date.fromisoformat(start_raw)
        end_date = date.fromisoformat(end_raw)
    except ValueError as exc:
        raise RuntimeError("Historical backfill planning dates must use YYYY-MM-DD") from exc
    if end_date < start_date:
        raise RuntimeError("Historical backfill end date must be on or after start date")

    plan_mode = os.getenv("AMFI_HISTORY_PLAN_MODE", "daily").strip().lower()
    if plan_mode == "hybrid":
        monthly_start_raw = os.getenv("AMFI_HISTORY_MONTHLY_START_DATE", "").strip()
        daily_start_raw = os.getenv("AMFI_HISTORY_DAILY_START_DATE", "").strip()
        if not monthly_start_raw or not daily_start_raw:
            raise RuntimeError(
                "Hybrid history planning requires AMFI_HISTORY_MONTHLY_START_DATE "
                "and AMFI_HISTORY_DAILY_START_DATE"
            )
        try:
            monthly_start_date = date.fromisoformat(monthly_start_raw)
            daily_start_date = date.fromisoformat(daily_start_raw)
        except ValueError as exc:
            raise RuntimeError("Hybrid history plan dates must use YYYY-MM-DD") from exc
        result = create_storage_optimized_history_plan(
            start_date,
            end_date,
            monthly_start_date,
            daily_start_date,
            (1, 2, 3),
        )
    elif plan_mode == "daily":
        result = create_history_backfill_plan(
            start_date,
            end_date,
            (1, 2, 3),
            max_window_days=7,
        )
    else:
        raise RuntimeError("AMFI_HISTORY_PLAN_MODE must be daily or hybrid")

    logger.warning(
        "amfi_history_backfill_plan_created",
        extra={
            "plan_mode": plan_mode,
            "checkpoints_created": result["checkpoints_created"],
            "checkpoints_already_present": result.get("checkpoints_already_present", 0),
            "checkpoints_paused": result.get("checkpoints_paused", 0),
            "monthly_windows_per_scheme_type": result.get("monthly_windows_per_scheme_type", 0),
            "daily_windows_per_scheme_type": result.get("daily_windows_per_scheme_type", result.get("windows_per_scheme_type", 0)),
            "network_requests_made": result["network_requests_made"],
        },
    )
    return result

def _maybe_run_historical_backfill_batch_from_environment() -> dict[str, Any] | None:
    """Run an explicitly enabled, bounded sequence of historical NAV batches."""
    if os.getenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "").strip().lower() != "true":
        return None
    if os.getenv("AMFI_HISTORY_CONTRACT_VERIFIED", "").strip().lower() != "true":
        raise RuntimeError(
            "Historical NAV execution requires AMFI_HISTORY_CONTRACT_VERIFIED=true"
        )
    if os.getenv("AMFI_HISTORY_BACKFILL_ENABLED", "").strip().lower() != "true":
        raise RuntimeError(
            "Historical NAV execution requires AMFI_HISTORY_BACKFILL_ENABLED=true"
        )

    limit_raw = os.getenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "1").strip()
    try:
        limit = int(limit_raw)
    except ValueError as exc:
        raise RuntimeError("Historical NAV batch limit must be an integer") from exc
    if not 1 <= limit <= 5:
        raise RuntimeError("Startup historical NAV batch limit must be between 1 and 5")

    total_raw = os.getenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", str(limit)).strip()
    try:
        max_windows = int(total_raw)
    except ValueError as exc:
        raise RuntimeError("Historical NAV max windows per start must be an integer") from exc
    if not 1 <= max_windows <= 200:
        raise RuntimeError("Historical NAV max windows per start must be between 1 and 200")

    stale_raw = os.getenv("AMFI_HISTORY_STALE_AFTER_MINUTES", "30").strip()
    try:
        stale_after_minutes = int(stale_raw)
    except ValueError as exc:
        raise RuntimeError("Historical NAV stale-worker threshold must be an integer") from exc
    if not 1 <= stale_after_minutes <= 240:
        raise RuntimeError("Historical NAV stale-worker threshold must be between 1 and 240 minutes")
    configured_stale_after_minutes = stale_after_minutes
    # AMFI history requests have a 60-second read timeout and bounded retries.
    # A one- or two-minute lease can reclaim a healthy in-flight request during
    # rolling deploys. Keep a safe minimum lease while retaining operator tuning.
    stale_after_minutes = max(15, stale_after_minutes)
    if stale_after_minutes != configured_stale_after_minutes:
        logger.warning(
            "amfi_history_stale_lease_clamped configured_minutes=%s effective_minutes=%s",
            configured_stale_after_minutes,
            stale_after_minutes,
        )

    selected = completed = failed = 0
    results: list[dict[str, Any]] = []
    while selected < max_windows:
        batch = run_history_backfill_batch(
            limit=min(limit, max_windows - selected),
            enabled=True,
            source_contract_verified=True,
            stale_after_minutes=stale_after_minutes,
        )
        results.extend(batch["results"])
        selected += batch["selected"]
        completed += batch["completed"]
        failed += batch["failed"]
        if batch["failed"] or batch["selected"] == 0 or batch["selected"] < min(
            limit, max_windows - (selected - batch["selected"])
        ):
            break

    status = (
        "partial_failure" if failed else
        "completed" if selected else
        "idle"
    )
    result = {
        "status": status,
        "selected": selected,
        "completed": completed,
        "failed": failed,
        "results": results,
        "max_attempts": 3,
    }

    # Historical backfill writes NAV observations directly rather than through
    # the daily refresh endpoint. Build the research cache only after every
    # non-paused checkpoint is settled, so rankings never freeze a partial run.
    research_refresh: dict[str, Any] = {
        "status": "deferred",
        "reason": "history_windows_remaining",
    }
    if failed == 0:
        history_status = history_backfill_status()
        unfinished = sum(
            int(group.get("windows", 0))
            for group in history_status.get("groups", [])
            if group.get("checkpoint_status") in {"pending", "running", "failed"}
        )
        if unfinished == 0:
            research_refresh = _refresh_research_snapshots_after_ingestion()
        else:
            research_refresh["unfinished_windows"] = unfinished
    result["research_snapshot_refresh"] = research_refresh

    first_failure = next(
        (item for item in results if item.get("status") == "failed"),
        {},
    )
    logger.warning(
        "amfi_history_backfill_batch_finished",
        extra={
            "status": status,
            "selected": selected,
            "completed": completed,
            "failed": failed,
            "batch_limit": limit,
            "max_windows_per_start": max_windows,
            "configured_stale_after_minutes": configured_stale_after_minutes,
            "effective_stale_after_minutes": stale_after_minutes,
            "first_error_class": first_failure.get("error_class"),
            "first_error_detail": first_failure.get("error_detail"),
        },
    )
    return result

def _maybe_refresh_research_after_history_completion() -> dict[str, Any]:
    """Refresh ranking snapshots only after all non-paused history work is settled."""
    status = history_backfill_status()
    blocking = [
        group for group in status.get("groups", [])
        if group.get("checkpoint_status") in {"pending", "failed", "running"}
    ]
    if blocking:
        logger.info(
            "research_snapshot_refresh_deferred_history_incomplete blocking_groups=%s",
            len(blocking),
        )
        return {"status": "deferred", "blocking_groups": len(blocking)}
    return _refresh_research_snapshots_after_ingestion()


def _log_research_refresh_task_result(task: asyncio.Task[Any]) -> None:
    try:
        result = task.result()
        logger.warning(
            "research_snapshot_refresh_after_history status=%s schemes=%s rows=%s",
            result.get("status"),
            result.get("schemes_processed"),
            result.get("snapshot_rows_written"),
        )
    except Exception:
        logger.exception("research_snapshot_refresh_after_history_failed")


def _log_history_backfill_task_result(task: asyncio.Task[Any]) -> None:
    """Consume and log the result of the non-blocking one-shot history worker."""
    try:
        result = task.result()
        logger.warning(
            "amfi_history_backfill_background_task_completed",
            extra={
                "status": result.get("status"),
                "selected": result.get("selected"),
                "completed": result.get("completed"),
                "failed": result.get("failed"),
                "research_snapshot_refresh_status": (result.get("research_snapshot_refresh") or {}).get("status"),
            },
        )
        if result.get("status") in {"completed", "idle"} and not result.get("failed"):
            refresh_task = asyncio.create_task(
                asyncio.to_thread(_maybe_refresh_research_after_history_completion)
            )
            refresh_task.add_done_callback(_log_research_refresh_task_result)
    except asyncio.CancelledError:
        logger.warning("amfi_history_backfill_background_task_cancelled")
    except Exception:
        logger.exception("amfi_history_backfill_background_task_failed")


def _scheme_taxonomy(scheme: Scheme) -> dict[str, str | None]:
    """Expose only allow-listed SEBI taxonomy, including the sub-category."""
    group = canonical_group(scheme.category_group)
    return {
        "category_group": group,
        "category": canonical_subcategory(group, scheme.category),
        "asset_class": canonical_asset_class(group, scheme.asset_class),
    }


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
        _maybe_plan_historical_backfill_from_environment()
        history_requested = (
            os.getenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "").strip().lower() == "true"
        )
        metadata_requested = (
            os.getenv("AMFI_SCHEME_METADATA_REFRESH_ON_START", "").strip().lower() == "true"
        )
        if history_requested and metadata_requested:
            raise RuntimeError(
                "Run either historical NAV backfill or scheme metadata refresh on a deployment, not both"
            )
        if metadata_requested:
            metadata_task = asyncio.create_task(
                asyncio.to_thread(_maybe_refresh_scheme_metadata_from_environment)
            )
            metadata_task.add_done_callback(_log_scheme_metadata_task_result)
        if history_requested:
            # Do not hold API readiness on AMFI's external HTTP response. The
            # bounded checkpoint worker runs in a background thread.
            history_task = asyncio.create_task(
                asyncio.to_thread(_maybe_run_historical_backfill_batch_from_environment)
            )
            history_task.add_done_callback(_log_history_backfill_task_result)
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


_authenticated_user_id: ContextVar[str | None] = ContextVar("authenticated_user_id", default=None)


@app.middleware("http")
async def supabase_user_authentication(request, call_next):
    """Validate browser sessions with Supabase Auth; never trust decoded JWT claims alone."""
    path = request.url.path
    if not path.startswith("/v1/") or path == "/v1/nav/refresh":
        return await call_next(request)

    # Retain the server-side operator key for existing trusted automation and tests.
    expected = os.getenv("API_KEY", "")
    supplied = request.headers.get("X-API-Key", "")
    if expected and len(expected) >= 32 and supplied and secrets.compare_digest(supplied, expected):
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        if not expected:
            return JSONResponse({"detail": "Server authentication is not configured."}, status_code=503)
        if len(expected) < 32 and supplied and secrets.compare_digest(supplied, expected):
            return JSONResponse({"detail": "Server operator key must contain at least 32 characters."}, status_code=503)
        return JSONResponse({"detail": "Please sign in to continue."}, status_code=401)

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        logger.error("supabase_auth_not_configured")
        return JSONResponse({"detail": "Sign-in is temporarily unavailable. Please contact the app administrator."}, status_code=503)

    token = authorization[7:].strip()
    if not token or len(token) > 8192:
        return JSONResponse({"detail": "Invalid or expired session. Please sign in again."}, status_code=401)

    try:
        response = await asyncio.to_thread(
            requests.get,
            f"{supabase_url}/auth/v1/user",
            headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
            timeout=(3, 8),
        )
        if response.status_code != 200:
            return JSONResponse({"detail": "Your session has expired. Please sign in again."}, status_code=401)
        user_id = str(response.json().get("id", "")).strip()
        if not user_id:
            return JSONResponse({"detail": "Unable to verify your account. Please sign in again."}, status_code=401)
    except requests.RequestException:
        logger.warning("supabase_auth_verification_unavailable", exc_info=True)
        return JSONResponse({"detail": "Sign-in verification is temporarily unavailable. Please retry."}, status_code=503)
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"detail": "Invalid sign-in response. Please sign in again."}, status_code=401)

    context_token = _authenticated_user_id.set(user_id)
    try:
        request.state.user_id = user_id
        return await call_next(request)
    finally:
        _authenticated_user_id.reset(context_token)


def require_api_key(x_api_key: str | None) -> None:
    """Permit a verified Supabase user or a trusted server-side operator key."""
    if _authenticated_user_id.get():
        return
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Server operator authentication is not configured")
    if len(expected) < 32:
        raise HTTPException(503, "Server operator key must contain at least 32 characters")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Sign in to access this endpoint")


def require_authenticated_user() -> str:
    """Return the verified Supabase identity; operator API keys cannot own user data."""
    user_id = _authenticated_user_id.get()
    if not user_id:
        raise HTTPException(401, "Sign in with a personal account to use your fund watchlist")
    return user_id


def require_operator_api_key(x_api_key: str | None) -> None:
    """Require the dedicated server operator key, even when a user session is present."""
    expected = os.getenv("API_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Server operator authentication is not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Operator key required for this action")


def _require_portfolio_owner(db: Any, portfolio_id: int) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(404, "Portfolio not found")
    user_id = _authenticated_user_id.get()
    # In production, the shared operator key is for operational endpoints only.
    # It must never act as a wildcard owner for private portfolio data.
    if not user_id and os.getenv("ENVIRONMENT", "").lower() == "production":
        raise HTTPException(401, "Sign in with a personal account to access portfolio data")
    if user_id and portfolio.owner_user_id != user_id:
        raise HTTPException(404, "Portfolio not found")
    return portfolio


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


def _refresh_scheme_metadata_from_amfi() -> dict[str, Any]:
    """Refresh scheme-master metadata from the current AMFI feed without NAV writes."""
    raw_payload, source_meta = _fetch_amfi_payload()
    try:
        payload = raw_payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise RuntimeError("AMFI scheme metadata feed is not valid UTF-8") from None
    records, report = parse_amfi_nav_text(payload)
    if report["records_valid"] < MINIMUM_VALID_RECORDS:
        raise RuntimeError(
            f"AMFI metadata feed had only {report['records_valid']} valid rows"
        )
    latest_nav_date = date.fromisoformat(report["max_nav_date"])
    nav_age_days = (date.today() - latest_nav_date).days
    if nav_age_days > MAX_NAV_STALENESS_DAYS:
        raise RuntimeError(
            f"AMFI metadata feed is stale by {nav_age_days} days"
        )
    metadata_records = [
        record for record in records
        if record.metadata_present or record.plan_type or record.option_type
    ]
    if not metadata_records:
        raise RuntimeError("AMFI feed contained no explicit scheme metadata to refresh")

    result = refresh_scheme_metadata(
        metadata_records,
        datetime.now(timezone.utc),
    )
    response = {
        "status": "refreshed",
        **result,
        "payload_sha256": report["payload_sha256"],
        "http_status": source_meta["http_status"],
        "bytes_received": source_meta["bytes_received"],
        "nav_as_of_date": report["max_nav_date"],
        "metadata_source_rows": len(metadata_records),
        "invalid_nav_rows": report["invalid_rows"],
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "nav_observations_written": 0,
    }
    logger.warning(
        "amfi_scheme_metadata_refresh_completed",
        extra={
            "scheme_records_seen": result["scheme_records_seen"],
            "scheme_rows_created": result["scheme_rows_created"],
            "scheme_rows_updated": result["scheme_rows_updated"],
            "category_group_populated": result["category_group_populated"],
            "category_unclassified": result["category_unclassified"],
            "plan_type_populated": result["plan_type_populated"],
            "option_type_populated": result["option_type_populated"],
            "payload_sha256": report["payload_sha256"],
        },
    )
    return response


def _maybe_refresh_scheme_metadata_from_environment() -> dict[str, Any] | None:
    """Run scheme metadata refresh only under two explicit deployment gates."""
    if os.getenv("AMFI_SCHEME_METADATA_REFRESH_ON_START", "").strip().lower() != "true":
        return None
    if os.getenv("AMFI_SCHEME_METADATA_REFRESH_ENABLED", "").strip().lower() != "true":
        raise RuntimeError(
            "Scheme metadata refresh requires AMFI_SCHEME_METADATA_REFRESH_ENABLED=true"
        )
    if os.getenv("AMFI_SCHEME_METADATA_CONTRACT_VERIFIED", "").strip().lower() != "true":
        raise RuntimeError(
            "Scheme metadata refresh requires AMFI_SCHEME_METADATA_CONTRACT_VERIFIED=true"
        )
    return _refresh_scheme_metadata_from_amfi()


def _log_scheme_metadata_task_result(task: asyncio.Task[Any]) -> None:
    try:
        result = task.result()
        logger.warning(
            "amfi_scheme_metadata_background_task_completed",
            extra={
                "status": result.get("status"),
                "scheme_records_seen": result.get("scheme_records_seen"),
                "scheme_rows_created": result.get("scheme_rows_created"),
                "scheme_rows_updated": result.get("scheme_rows_updated"),
                "category_group_populated": result.get("category_group_populated"),
            },
        )
    except asyncio.CancelledError:
        logger.warning("amfi_scheme_metadata_background_task_cancelled")
    except Exception:
        logger.exception("amfi_scheme_metadata_background_task_failed")


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
                    amc=record.amc, structure=record.structure,
                    category_group=record.category_group, category=record.category,
                    asset_class=record.asset_class,
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
                if record.amc:
                    scheme.amc = record.amc
                if record.metadata_present:
                    scheme.structure = record.structure
                    scheme.category_group = record.category_group
                    scheme.category = record.category
                    scheme.asset_class = record.asset_class
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
        except Exception as exc:
            # Preserve a useful production diagnostic without logging SQL parameters,
            # connection strings, or source payload contents.
            database_error = getattr(exc, "orig", None)
            logger.error(
                "nav_snapshot_persistence_failed error_type=%s database_error_type=%s",
                type(exc).__name__,
                type(database_error).__name__ if database_error is not None else "none",
            )
            raise HTTPException(500, "NAV snapshot persistence failed; diagnostic error types were recorded; existing accepted data was preserved where the transaction rolled back") from None
        snapshot = persisted["snapshot"]
        research_snapshot_refresh = _refresh_research_snapshots_after_ingestion()
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
            "research_snapshot_refresh": research_snapshot_refresh,
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


@app.post("/v1/schemes/metadata/refresh")
def refresh_scheme_metadata_endpoint(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Refresh the shared scheme master from AMFI without writing NAV observations."""
    require_api_key(x_api_key)
    try:
        return _refresh_scheme_metadata_from_amfi()
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        logger.warning(
            "amfi_scheme_metadata_refresh_failed error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            502,
            f"AMFI scheme metadata refresh failed: {type(exc).__name__}; existing metadata was not changed where the transaction rolled back",
        ) from None


@app.get("/v1/nav/facets")
def nav_scheme_facets(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, list[str]]:
    """Return only SEBI-allow-listed groups, sub-categories and asset classes."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        def values(column: Any) -> list[str]:
            rows = db.execute(
                select(column).where(column.is_not(None), column != "").distinct().order_by(column)
            ).scalars().all()
            return [str(value) for value in rows if str(value).strip()]

        group_rows = db.execute(
            select(Scheme.category_group, Scheme.asset_class).distinct()
        ).all()
        valid_groups = {
            normalized
            for group, _asset in group_rows
            if (normalized := canonical_group(group)) is not None
        }
        category_rows = db.execute(
            select(Scheme.category_group, Scheme.category)
            .where(Scheme.category_group.is_not(None), Scheme.category.is_not(None), Scheme.category != "")
            .distinct()
        ).all()
        valid_subcategories = sorted({
            category
            for group, raw_category in category_rows
            if (category := canonical_subcategory(group, raw_category)) is not None
        })
        valid_assets = sorted({
            asset
            for group, asset in group_rows
            if canonical_asset_class(group, asset) is not None
        })
        return {
            "amcs": values(Scheme.amc),
            "categories": sorted(valid_groups),
            "sub_categories": valid_subcategories,
            "asset_classes": valid_assets,
            "plan_types": values(Scheme.plan_type),
            "option_types": values(Scheme.option_type),
        }

@app.get("/v1/nav/schemes")
def list_schemes(
    q: str | None = None,
    amc: str | None = None,
    category: str | None = None,
    category_group: str | None = None,
    sub_category: str | None = None,
    asset_class: str | None = None,
    plan_type: str | None = None,
    option_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Search and filter the complete ingested scheme master with stable pagination."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        query = select(Scheme)
        if q:
            term = q.strip()[:120]
            if term:
                query = query.where(
                    Scheme.scheme_code == int(term)
                    if term.isdigit()
                    else or_(
                        Scheme.scheme_name.ilike(f"%{term}%"),
                        Scheme.amc.ilike(f"%{term}%"),
                        Scheme.isin_growth.ilike(f"%{term}%"),
                        Scheme.isin_dividend_reinvestment.ilike(f"%{term}%"),
                    )
                )
        for column, value in (
            (Scheme.amc, amc),
            (Scheme.asset_class, asset_class),
            (Scheme.plan_type, plan_type),
            (Scheme.option_type, option_type),
        ):
            if value and value.strip():
                query = query.where(column.ilike(value.strip()[:120]))
        if category_group:
            query = query.where(Scheme.category_group.in_(scheme_group_filter_values(category_group)))
        selected_subcategory = sub_category or category
        if selected_subcategory:
            query = query.where(Scheme.category.in_(subcategory_filter_values(category_group, selected_subcategory)))
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        latest_id = (
            select(NavObservation.id)
            .where(NavObservation.scheme_code == Scheme.scheme_code)
            .order_by(desc(NavObservation.nav_date), desc(NavObservation.id))
            .limit(1)
            .correlate(Scheme)
            .scalar_subquery()
        )
        rows = db.execute(
            query.outerjoin(NavObservation, NavObservation.id == latest_id)
            .add_columns(NavObservation)
            .order_by(Scheme.scheme_name, Scheme.scheme_code)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "count": len(rows),
            "total_matching": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "scheme_code": scheme.scheme_code,
                    "scheme_name": scheme.scheme_name,
                    "amc": scheme.amc,
                    "isin_growth": scheme.isin_growth,
                    "isin_dividend_reinvestment": scheme.isin_dividend_reinvestment,
                    "plan_type": scheme.plan_type,
                    "option_type": scheme.option_type,
                    **_scheme_taxonomy(scheme),
                    "latest_nav": str(nav.nav_value) if nav else None,
                    "nav_date": nav.nav_date.isoformat() if nav else None,
                }
                for scheme, nav in rows
            ],
        }

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
            "amc": scheme.amc, "structure": scheme.structure, **_scheme_taxonomy(scheme),
            "plan_type": scheme.plan_type, "option_type": scheme.option_type,
            "first_seen_at": scheme.first_seen_at.isoformat(),
            "last_seen_at": scheme.last_seen_at.isoformat(),
            "latest_nav": str(latest.nav_value) if latest else None,
            "latest_nav_date": latest.nav_date.isoformat() if latest else None,
            "observations_in_window": len(rows),
            "window_start": rows[0].nav_date.isoformat() if rows else None,
            "window_end": rows[-1].nav_date.isoformat() if rows else None,
            "nav_series": [{"date": row.nav_date.isoformat(), "nav": float(row.nav_value)} for row in rows],
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
                **_scheme_taxonomy(scheme),
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


@app.post("/v1/analytics/screener/refresh")
def refresh_fund_research_snapshots(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Rebuild shared, source-backed ranking snapshots; restricted to the operator key."""
    expected = os.getenv("API_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Server operator authentication is not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Operator key required to rebuild research snapshots")

    refreshed_at = datetime.now(timezone.utc)
    windows = (365, 1095, 1825, 3650)
    history_floor = refreshed_at.date() - timedelta(days=max(windows))
    snapshot_rows: list[FundResearchSnapshot] = []
    schemes_processed = 0
    min_as_of: date | None = None
    max_as_of: date | None = None

    def append_scheme_snapshot(
        scheme_code: int,
        points: list[tuple[date, float]],
    ) -> None:
        nonlocal schemes_processed, min_as_of, max_as_of
        if not points:
            return
        schemes_processed += 1
        as_of = points[-1][0]
        min_as_of = as_of if min_as_of is None else min(min_as_of, as_of)
        max_as_of = as_of if max_as_of is None else max(max_as_of, as_of)
        for window_days in windows:
            cutoff = as_of - timedelta(days=window_days)
            window_points = [(d, value) for d, value in points if d >= cutoff]
            metrics = research_metrics(window_points)
            period = metrics.get("period_returns", {})
            rolling = metrics.get("rolling_1y", {})
            compact_metrics = {
                "status": metrics.get("status"),
                "observations": metrics.get("observations", 0),
                "start_date": metrics.get("start_date"),
                "end_date": metrics.get("end_date"),
                "latest_nav": metrics.get("latest_nav"),
                "total_return": metrics.get("total_return"),
                "period_returns": period,
                "rolling_1y": {
                    "status": rolling.get("status"),
                    "observations": rolling.get("observations", 0),
                    "positive_window_rate": rolling.get("positive_window_rate"),
                },
                "monthly_returns": metrics.get("monthly_returns", []) if window_days == 365 else [],
                "methodology": "NAV-only research snapshot; no benchmark TRI or distribution adjustment.",
            }
            snapshot_rows.append(FundResearchSnapshot(
                scheme_code=scheme_code,
                window_days=window_days,
                nav_as_of_date=as_of,
                refreshed_at=refreshed_at,
                observations=int(metrics.get("observations", 0)),
                metrics_json=json.dumps(compact_metrics, ensure_ascii=False, allow_nan=False),
                return_1m=period.get("1M"),
                return_3m=period.get("3M"),
                return_6m=period.get("6M"),
                return_1y=period.get("1Y"),
                return_3y=period.get("3Y"),
                return_5y=period.get("5Y"),
                cagr=metrics.get("cagr"),
                volatility=metrics.get("annualized_volatility"),
                sharpe_ratio=metrics.get("sharpe_ratio"),
                sortino_ratio=metrics.get("sortino_ratio"),
                max_drawdown=metrics.get("max_drawdown"),
                positive_month_rate=metrics.get("positive_month_rate"),
                rolling_1y_positive_rate=rolling.get("positive_window_rate"),
            ))

    with SessionLocal() as db:
        statement = (
            select(NavObservation.scheme_code, NavObservation.nav_date, NavObservation.nav_value)
            .where(NavObservation.nav_date >= history_floor)
            .order_by(NavObservation.scheme_code, NavObservation.nav_date)
            .execution_options(stream_results=True, yield_per=10000)
        )
        result = db.execute(statement)
        current_code: int | None = None
        current_points: list[tuple[date, float]] = []
        for scheme_code, nav_date, nav_value in result:
            if current_code is not None and scheme_code != current_code:
                append_scheme_snapshot(current_code, current_points)
                current_points = []
            current_code = scheme_code
            current_points.append((nav_date, float(nav_value)))
        if current_code is not None:
            append_scheme_snapshot(current_code, current_points)

        if not snapshot_rows:
            raise HTTPException(409, "No NAV history is available to build research snapshots")

        # Delete + insert is one transaction: readers see the old complete
        # snapshot set until the replacement set commits successfully.
        db.execute(delete(FundResearchSnapshot))
        for offset in range(0, len(snapshot_rows), 2000):
            db.add_all(snapshot_rows[offset:offset + 2000])
            db.flush()
        db.commit()

    return {
        "status": "refreshed",
        "schemes_processed": schemes_processed,
        "snapshot_rows_written": len(snapshot_rows),
        "windows_days": list(windows),
        "nav_as_of_date_min": min_as_of.isoformat() if min_as_of else None,
        "nav_as_of_date_max": max_as_of.isoformat() if max_as_of else None,
        "refreshed_at": refreshed_at.isoformat(),
        "methodology_version": "nav-research-v1",
        "note": "Snapshots use stored AMFI NAV observations only; no benchmark TRI or distribution adjustment is implied.",
    }


def _refresh_research_snapshots_after_ingestion() -> dict[str, Any]:
    """Refresh global rankings after a committed daily NAV ingest.

    A research snapshot failure must not undo accepted NAV rows. Surface a safe
    status to the operator so the rebuild can be retried independently.
    """
    if not _research_snapshot_refresh_lock.acquire(blocking=False):
        return {"status": "in_progress"}
    try:
        result = refresh_fund_research_snapshots(x_api_key=os.getenv("API_KEY"))
        logger.info(
            "research_snapshot_refresh_after_nav_ingestion status=refreshed schemes=%s rows=%s",
            result.get("schemes_processed"),
            result.get("snapshot_rows_written"),
        )
        return {
            "status": "refreshed",
            "schemes_processed": result.get("schemes_processed"),
            "snapshot_rows_written": result.get("snapshot_rows_written"),
            "refreshed_at": result.get("refreshed_at"),
        }
    except Exception as exc:
        logger.warning(
            "research_snapshot_refresh_after_nav_ingestion_failed error_type=%s",
            type(exc).__name__,
            exc_info=True,
        )
        return {"status": "deferred", "error_type": type(exc).__name__}
    finally:
        _research_snapshot_refresh_lock.release()


@app.get("/v1/analytics/screener")
def fund_screener(
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=160),
    category_group: str | None = Query(default=None, max_length=80),
    sub_category: str | None = Query(default=None, max_length=120),
    asset_class: str | None = Query(default=None, max_length=40),
    plan_type: str | None = Query(default=None, max_length=20),
    option_type: str | None = Query(default=None, max_length=20),
    days: int = Query(default=1095, ge=365, le=3650),
    sort_by: Literal[
        "return_1m", "return_3m", "return_6m", "return_1y", "return_3y", "return_5y", "cagr", "volatility",
        "sharpe_ratio", "sortino_ratio", "max_drawdown",
        "positive_month_rate", "rolling_1y_positive_rate",
    ] = "return_1y",
    sort_order: Literal["asc", "desc"] = "desc",
    min_observations: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Globally ranked screener over the latest committed precomputed NAV snapshots."""
    require_api_key(x_api_key)
    if days not in {365, 1095, 1825, 3650}:
        raise HTTPException(422, "days must be one of 365, 1095, 1825 or 3650")

    # Bootstrap the shared ranking cache on the first authenticated research visit.
    # This is idempotent and only runs when no precomputed snapshot exists.
    with SessionLocal() as db:
        has_research_snapshots = db.execute(
            select(func.max(FundResearchSnapshot.refreshed_at))
        ).scalar_one()
    if has_research_snapshots is None:
        bootstrap = _refresh_research_snapshots_after_ingestion()
        if bootstrap.get("status") != "refreshed":
            raise HTTPException(
                503,
                "Fund rankings are being prepared from accepted NAV history. Please retry shortly.",
            )

    sort_columns = {
        "return_1m": FundResearchSnapshot.return_1m,
        "return_3m": FundResearchSnapshot.return_3m,
        "return_6m": FundResearchSnapshot.return_6m,
        "return_1y": FundResearchSnapshot.return_1y,
        "return_3y": FundResearchSnapshot.return_3y,
        "return_5y": FundResearchSnapshot.return_5y,
        "cagr": FundResearchSnapshot.cagr,
        "volatility": FundResearchSnapshot.volatility,
        "sharpe_ratio": FundResearchSnapshot.sharpe_ratio,
        "sortino_ratio": FundResearchSnapshot.sortino_ratio,
        "max_drawdown": FundResearchSnapshot.max_drawdown,
        "positive_month_rate": FundResearchSnapshot.positive_month_rate,
        "rolling_1y_positive_rate": FundResearchSnapshot.rolling_1y_positive_rate,
    }
    sort_column = sort_columns[sort_by]
    ordering = sort_column.desc().nullslast() if sort_order == "desc" else sort_column.asc().nullslast()
    category_ranked = (
        select(
            FundResearchSnapshot.scheme_code.label("scheme_code"),
            func.rank().over(
                partition_by=(
                    Scheme.category_group,
                    Scheme.category,
                    Scheme.plan_type,
                    Scheme.option_type,
                ),
                order_by=ordering,
            ).label("category_rank"),
        )
        .join(Scheme, Scheme.scheme_code == FundResearchSnapshot.scheme_code)
        .where(
            FundResearchSnapshot.window_days == days,
            FundResearchSnapshot.observations >= min_observations,
        )
        .subquery()
    )

    with SessionLocal() as db:
        query = (
            select(FundResearchSnapshot, Scheme, category_ranked.c.category_rank)
            .join(Scheme, Scheme.scheme_code == FundResearchSnapshot.scheme_code)
            .join(category_ranked, category_ranked.c.scheme_code == Scheme.scheme_code)
            .where(
                FundResearchSnapshot.window_days == days,
                FundResearchSnapshot.observations >= min_observations,
            )
        )
        if q:
            term = q.strip()[:120]
            if term.isdigit():
                query = query.where(Scheme.scheme_code == int(term))
            else:
                pattern = f"%{term}%"
                query = query.where(or_(
                    Scheme.scheme_name.ilike(pattern),
                    Scheme.amc.ilike(pattern),
                    Scheme.isin_growth.ilike(pattern),
                    Scheme.isin_dividend_reinvestment.ilike(pattern),
                ))
        if category_group:
            query = query.where(Scheme.category_group.in_(scheme_group_filter_values(category_group)))
        selected_subcategory = sub_category or category
        if selected_subcategory:
            query = query.where(Scheme.category.in_(subcategory_filter_values(category_group, selected_subcategory)))
        if asset_class:
            query = query.where(Scheme.asset_class == asset_class)
        if plan_type:
            query = query.where(Scheme.plan_type == plan_type)
        if option_type:
            query = query.where(Scheme.option_type == option_type)

        total = db.execute(
            select(func.count()).select_from(query.subquery())
        ).scalar_one()
        rows = db.execute(
            query.order_by(ordering, Scheme.scheme_name.asc(), Scheme.scheme_code.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        latest_refresh = db.execute(
            select(func.max(FundResearchSnapshot.refreshed_at)).where(
                FundResearchSnapshot.window_days == days
            )
        ).scalar_one()
        if latest_refresh is None:
            raise HTTPException(
                503,
                "Global research ranking is not ready yet. The scheduled research snapshot has not completed.",
            )

        items = []
        for snapshot, scheme, within_category_rank in rows:
            metrics = json.loads(snapshot.metrics_json)
            period_returns = metrics.get("period_returns") or {}
            items.append({
                "rank": offset + len(items) + 1,
                "category_rank": int(within_category_rank) if within_category_rank is not None else None,
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
                **_scheme_taxonomy(scheme),
                "plan_type": scheme.plan_type,
                "option_type": scheme.option_type,
                "latest_nav": str(metrics.get("latest_nav")) if metrics.get("latest_nav") is not None else None,
                "nav_date": snapshot.nav_as_of_date.isoformat(),
                "observations": snapshot.observations,
                "return_1m": snapshot.return_1m,
                "return_3m": period_returns.get("3M"),
                "return_6m": period_returns.get("6M"),
                "return_1y": snapshot.return_1y,
                "return_3y": snapshot.return_3y,
                "return_5y": period_returns.get("5Y"),
                "cagr": snapshot.cagr,
                "volatility": snapshot.volatility,
                "sharpe_ratio": snapshot.sharpe_ratio,
                "sortino_ratio": snapshot.sortino_ratio,
                "max_drawdown": snapshot.max_drawdown,
                "positive_month_rate": snapshot.positive_month_rate,
                "rolling_1y_positive_rate": snapshot.rolling_1y_positive_rate,
                "metrics_status": metrics.get("status"),
            })

        return {
            "count": len(items),
            "total_matching": total,
            "limit": limit,
            "offset": offset,
            "days_requested": days,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "min_observations": min_observations,
            "refreshed_at": latest_refresh.isoformat(),
            "items": items,
            "sorting_note": "Ranks are calculated across all matching stored research snapshots before pagination; ties use scheme name and scheme code. Only observed NAV data is used.",
            "classification_coverage": {
                "category_populated": sum(bool(item["category"]) for item in items),
                "asset_class_populated": sum(bool(item["asset_class"]) for item in items),
                "plan_type_populated": sum(bool(item["plan_type"]) for item in items),
                "option_type_populated": sum(bool(item["option_type"]) for item in items),
            },
            "limitations": [
                "Metrics use stored AMFI NAV observations and are not distribution-adjusted total returns.",
                "Benchmark TRI, alpha, beta, tracking error and information ratio are unavailable until verified benchmark total-return data is integrated.",
                "Category and asset-class filters depend on independently verified scheme classification metadata.",
                "The as-of NAV date can differ by scheme; inspect nav_date and observations before comparing funds.",
            ],
        }


@app.get("/v1/analytics/monthly-leaderboard")
def monthly_fund_leaderboard(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    category_group: str | None = Query(default=None, max_length=80),
    sub_category: str | None = Query(default=None, max_length=120),
    plan_type: str = Query(default="Direct", pattern="^(Direct|Regular)$"),
    option_type: str = Query(default="Growth", pattern="^(Growth|IDCW)$"),
    limit: int = Query(default=3, ge=1, le=20),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Rank completed calendar-month NAV returns and show within-category rank movement."""
    require_api_key(x_api_key)
    current_month = date.today().replace(day=1)
    previous_month_end = current_month - timedelta(days=1)
    selected_month = month or previous_month_end.strftime("%Y-%m")
    try:
        selected_start = datetime.strptime(selected_month + "-01", "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "month must be a valid YYYY-MM calendar month") from None
    if selected_start >= current_month:
        raise HTTPException(422, "Monthly leaderboard only includes completed calendar months")
    previous_month = (selected_start.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    query = (
        select(FundResearchSnapshot, Scheme)
        .join(Scheme, Scheme.scheme_code == FundResearchSnapshot.scheme_code)
        .where(
            FundResearchSnapshot.window_days == 365,
            Scheme.plan_type == plan_type,
            Scheme.option_type == option_type,
        )
    )
    if category_group:
        query = query.where(Scheme.category_group.in_(scheme_group_filter_values(category_group)))
    if sub_category:
        query = query.where(Scheme.category.in_(subcategory_filter_values(category_group, sub_category)))

    with SessionLocal() as db:
        latest_refresh = db.execute(
            select(func.max(FundResearchSnapshot.refreshed_at)).where(FundResearchSnapshot.window_days == 365)
        ).scalar_one()
    if latest_refresh is None:
        bootstrap = _refresh_research_snapshots_after_ingestion()
        if bootstrap.get("status") != "refreshed":
            raise HTTPException(
                503,
                "Monthly fund rankings are being prepared from accepted NAV history. Please retry shortly.",
            )

    with SessionLocal() as db:
        latest_refresh = db.execute(
            select(func.max(FundResearchSnapshot.refreshed_at)).where(FundResearchSnapshot.window_days == 365)
        ).scalar_one()
        if latest_refresh is None:
            raise HTTPException(503, "Monthly research snapshots are not ready. Refresh research snapshots first.")
        rows = db.execute(query).all()

    current_items: list[dict[str, Any]] = []
    previous_returns: dict[int, float] = {}
    for snapshot, scheme in rows:
        try:
            monthly_rows = json.loads(snapshot.metrics_json).get("monthly_returns") or []
        except (TypeError, ValueError):
            monthly_rows = []
        monthly_map = {
            str(item.get("month")): item.get("return")
            for item in monthly_rows
            if isinstance(item, dict) and item.get("month") and item.get("return") is not None
        }
        current_value = monthly_map.get(selected_month)
        if current_value is not None:
            taxonomy = _scheme_taxonomy(scheme)
            if not taxonomy.get("category_group"):
                continue
            current_items.append({
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
                **taxonomy,
                "plan_type": scheme.plan_type,
                "option_type": scheme.option_type,
                "monthly_return": float(current_value),
                "nav_date": snapshot.nav_as_of_date.isoformat(),
                "observations": snapshot.observations,
            })
        if monthly_map.get(previous_month) is not None:
            previous_returns[scheme.scheme_code] = float(monthly_map[previous_month])

    current_items.sort(key=lambda item: (-item["monthly_return"], item["scheme_name"].casefold(), item["scheme_code"]))
    previous_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for _snapshot, scheme in rows:
        value = previous_returns.get(scheme.scheme_code)
        if value is None:
            continue
        taxonomy = _scheme_taxonomy(scheme)
        if not taxonomy.get("category_group"):
            continue
        key = (taxonomy.get("category_group"), taxonomy.get("category"), scheme.plan_type, scheme.option_type)
        previous_groups.setdefault(key, []).append({"scheme_code": scheme.scheme_code, "value": value})
    previous_category_ranks: dict[int, int] = {}
    for group_rows in previous_groups.values():
        group_rows.sort(key=lambda item: (-item["value"], item["scheme_code"]))
        for rank_value, item in enumerate(group_rows, start=1):
            previous_category_ranks[item["scheme_code"]] = rank_value

    category_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in current_items:
        key = (item["category_group"], item["category"], item["plan_type"], item["option_type"])
        category_groups.setdefault(key, []).append(item)
    for group_rows in category_groups.values():
        group_rows.sort(key=lambda item: (-item["monthly_return"], item["scheme_name"].casefold(), item["scheme_code"]))
        for rank_value, item in enumerate(group_rows, start=1):
            item["category_rank"] = rank_value
            old_rank = previous_category_ranks.get(item["scheme_code"])
            item["previous_category_rank"] = old_rank
            item["rank_change"] = old_rank - rank_value if old_rank is not None else None

    for rank_value, item in enumerate(current_items, start=1):
        item["rank"] = rank_value
    visible = current_items[:limit]
    return {
        "month": selected_month,
        "previous_month": previous_month,
        "plan_type": plan_type,
        "option_type": option_type,
        "category_group": canonical_group(category_group) if category_group else None,
        "count": len(current_items),
        "items": visible,
        "refreshed_at": latest_refresh.isoformat(),
        "methodology": (
            "Completed calendar-month NAV return from the last observed NAV in the prior calendar month "
            "to the last observed NAV in the selected month. No interpolation or dividend adjustment. "
            "Rank movement compares the same scheme's within-subcategory rank with the prior month."
        ),
        "limitations": [
            "Only schemes with a stored 365-day research snapshot and both month-end observations are ranked.",
            "A scheme's displayed NAV date may differ from the calendar month-end because AMFI publishes only observed NAV dates.",
            "Rank movement is unavailable for schemes without a comparable prior-month rank.",
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


class WatchlistCreate(BaseModel):
    scheme_code: int = Field(gt=0)


class BenchmarkImportRequest(BaseModel):
    benchmark_code: str = Field(min_length=2, max_length=80, pattern="^[A-Z0-9][A-Z0-9_-]+$")
    benchmark_name: str = Field(min_length=2, max_length=240)
    variant: Literal["TRI", "NTR"]
    csv_text: str = Field(min_length=10, max_length=5_000_000)

    @model_validator(mode="after")
    def normalize_benchmark_identity(self) -> "BenchmarkImportRequest":
        self.benchmark_code = self.benchmark_code.strip().upper()
        self.benchmark_name = self.benchmark_name.strip()
        if not self.benchmark_name:
            raise ValueError("benchmark name cannot be blank")
        return self


class HoldingShock(BaseModel):
    scheme_code: int = Field(gt=0)
    shock_pct: Decimal = Field(ge=Decimal("-100"), le=Decimal("100"))


class GoalCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    target_amount_today: Decimal = Field(gt=Decimal("0"), le=Decimal("100000000000"))
    target_date: date
    current_amount: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("100000000000"))
    linked_portfolio_id: int | None = Field(default=None, gt=0)
    monthly_contribution: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1000000000"))
    inflation_rate: float = Field(default=0.06, ge=0, le=0.20)
    annual_return_low: float = Field(default=0.04, ge=-0.20, le=0.30)
    annual_return_base: float = Field(default=0.10, ge=-0.20, le=0.35)
    annual_return_high: float = Field(default=0.14, ge=-0.20, le=0.40)

    @model_validator(mode="after")
    def validate_goal(self) -> "GoalCreateRequest":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("goal name cannot be blank")
        if self.target_date <= date.today():
            raise ValueError("target date must be in the future")
        if not self.annual_return_low <= self.annual_return_base <= self.annual_return_high:
            raise ValueError("return assumptions must satisfy low <= base <= high")
        return self


class PortfolioStressRequest(BaseModel):
    scenario_name: str = Field(min_length=2, max_length=120)
    shocks: list[HoldingShock] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_scenario(self) -> "PortfolioStressRequest":
        self.scenario_name = self.scenario_name.strip()
        if not self.scenario_name:
            raise ValueError("scenario name cannot be blank")
        codes = [item.scheme_code for item in self.shocks]
        if len(codes) != len(set(codes)):
            raise ValueError("each scheme can appear only once in a stress scenario")
        return self


class HoldingsImportRequest(BaseModel):
    scheme_code: int = Field(gt=0)
    as_of_date: date
    source_document_url: str = Field(min_length=12, max_length=1000)
    source_document_sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")
    csv_text: str = Field(min_length=10, max_length=5_000_000)

    @model_validator(mode="after")
    def validate_holdings_source(self) -> "HoldingsImportRequest":
        self.source_document_url = self.source_document_url.strip()
        self.source_document_sha256 = self.source_document_sha256.lower()
        if not self.source_document_url.startswith("https://"):
            raise ValueError("holdings source document must use an HTTPS URL")
        return self


class SchemeBenchmarkAssignmentCreate(BaseModel):
    scheme_code: int = Field(gt=0)
    benchmark_code: str = Field(min_length=2, max_length=80, pattern="^[A-Z0-9][A-Z0-9_-]+$")
    tier: int = Field(ge=1, le=2)
    valid_from: date
    valid_to: date | None = None
    source_document_url: str = Field(min_length=12, max_length=1000)
    source_document_sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")

    @model_validator(mode="after")
    def validate_assignment_evidence(self) -> "SchemeBenchmarkAssignmentCreate":
        self.benchmark_code = self.benchmark_code.strip().upper()
        self.source_document_url = self.source_document_url.strip()
        self.source_document_sha256 = self.source_document_sha256.lower()
        if not self.source_document_url.startswith("https://"):
            raise ValueError("benchmark mapping evidence must use an HTTPS source document URL")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from")
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


@app.get("/v1/watchlist")
def list_fund_watchlist() -> dict[str, Any]:
    """Return only the verified user's saved funds and their latest stored NAV."""
    user_id = require_authenticated_user()
    with SessionLocal() as db:
        rows = db.execute(
            select(FundWatchlistItem, Scheme)
            .join(Scheme, Scheme.scheme_code == FundWatchlistItem.scheme_code)
            .where(FundWatchlistItem.owner_user_id == user_id)
            .order_by(desc(FundWatchlistItem.created_at), FundWatchlistItem.id.desc())
        ).all()
        codes = [item.scheme_code for item, _ in rows]
        latest_by_code: dict[int, NavObservation] = {}
        if codes:
            latest_dates = (
                select(
                    NavObservation.scheme_code.label("scheme_code"),
                    func.max(NavObservation.nav_date).label("latest_date"),
                )
                .where(NavObservation.scheme_code.in_(codes))
                .group_by(NavObservation.scheme_code)
                .subquery()
            )
            latest_rows = db.execute(
                select(NavObservation).join(
                    latest_dates,
                    (NavObservation.scheme_code == latest_dates.c.scheme_code)
                    & (NavObservation.nav_date == latest_dates.c.latest_date),
                )
            ).scalars().all()
            latest_by_code = {nav.scheme_code: nav for nav in latest_rows}
        return {
            "count": len(rows),
            "items": [
                {
                    "scheme_code": item.scheme_code,
                    "scheme_name": scheme.scheme_name,
                    "plan_type": scheme.plan_type,
                    "option_type": scheme.option_type,
                    **_scheme_taxonomy(scheme),
                    "added_at": item.created_at.isoformat(),
                    "latest_nav": str(latest_by_code[item.scheme_code].nav_value)
                    if item.scheme_code in latest_by_code else None,
                    "nav_date": latest_by_code[item.scheme_code].nav_date.isoformat()
                    if item.scheme_code in latest_by_code else None,
                }
                for item, scheme in rows
            ],
        }


@app.post("/v1/watchlist", status_code=201)
def add_fund_to_watchlist(payload: WatchlistCreate) -> dict[str, Any]:
    """Save a scheme for the verified user; duplicate additions are explicit conflicts."""
    user_id = require_authenticated_user()
    with SessionLocal() as db:
        if db.get(Scheme, payload.scheme_code) is None:
            raise HTTPException(404, "Scheme code not found")
        current_count = db.execute(
            select(func.count()).select_from(FundWatchlistItem).where(
                FundWatchlistItem.owner_user_id == user_id
            )
        ).scalar_one()
        if current_count >= 500:
            raise HTTPException(409, "A watchlist can contain at most 500 funds")
        item = FundWatchlistItem(
            owner_user_id=user_id,
            scheme_code=payload.scheme_code,
            created_at=datetime.now(timezone.utc),
        )
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This fund is already in your watchlist") from None
        return {
            "scheme_code": item.scheme_code,
            "status": "added",
            "added_at": item.created_at.isoformat(),
        }


@app.delete("/v1/watchlist/{scheme_code}")
def remove_fund_from_watchlist(scheme_code: int) -> dict[str, Any]:
    """Remove only the authenticated user's saved copy of a fund."""
    user_id = require_authenticated_user()
    with SessionLocal() as db:
        item = db.execute(
            select(FundWatchlistItem).where(
                FundWatchlistItem.owner_user_id == user_id,
                FundWatchlistItem.scheme_code == scheme_code,
            )
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(404, "Watchlist item not found")
        db.delete(item)
        db.commit()
        return {"scheme_code": scheme_code, "status": "removed"}


@app.get("/v1/benchmarks")
def list_benchmarks(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """List benchmark variants and their stored observation coverage."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        indices = db.execute(
            select(BenchmarkIndex).order_by(BenchmarkIndex.provider, BenchmarkIndex.benchmark_name, BenchmarkIndex.variant)
        ).scalars().all()
        items = []
        for index in indices:
            coverage = db.execute(
                select(
                    func.count(BenchmarkObservation.id),
                    func.min(BenchmarkObservation.observation_date),
                    func.max(BenchmarkObservation.observation_date),
                ).where(BenchmarkObservation.benchmark_code == index.benchmark_code)
            ).one()
            items.append({
                "benchmark_code": index.benchmark_code,
                "benchmark_name": index.benchmark_name,
                "provider": index.provider,
                "variant": index.variant,
                "source_url": index.source_url,
                "observations": coverage[0],
                "first_date": coverage[1].isoformat() if coverage[1] else None,
                "last_date": coverage[2].isoformat() if coverage[2] else None,
                "last_seen_at": index.last_seen_at.isoformat(),
            })
        return {"count": len(items), "items": items}


@app.post("/v1/benchmarks/import-csv")
def import_benchmark_csv(
    payload: BenchmarkImportRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Import an official Nifty Indices TRI/NTR CSV export with correction provenance."""
    require_operator_api_key(x_api_key)
    try:
        points, report = parse_nifty_tri_csv(payload.csv_text, payload.variant)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    source_name = report.get("source_index_name")
    def normalise_name(value: str) -> str:
        return "".join(ch.lower() for ch in value if ch.isalnum())

    if source_name and normalise_name(source_name) != normalise_name(payload.benchmark_name):
        raise HTTPException(422, "CSV index name does not match the requested benchmark name")

    source_sha256 = hashlib.sha256(payload.csv_text.encode("utf-8")).hexdigest()
    retrieved_at = datetime.now(timezone.utc)
    inserted = corrected = unchanged = 0

    with SessionLocal() as db:
        benchmark = db.get(BenchmarkIndex, payload.benchmark_code)
        if benchmark is not None and (
            benchmark.variant != payload.variant
            or normalise_name(benchmark.benchmark_name) != normalise_name(payload.benchmark_name)
        ):
            raise HTTPException(409, "Benchmark code already exists with a different name or return variant")
        if benchmark is None:
            benchmark = BenchmarkIndex(
                benchmark_code=payload.benchmark_code,
                benchmark_name=payload.benchmark_name,
                provider="NSE Indices Ltd.",
                variant=payload.variant,
                source_url=NIFTY_HISTORICAL_DATA_URL,
                created_at=retrieved_at,
                last_seen_at=retrieved_at,
            )
            db.add(benchmark)
            db.flush()
        else:
            benchmark.last_seen_at = retrieved_at

        existing_rows = db.execute(
            select(BenchmarkObservation).where(
                BenchmarkObservation.benchmark_code == payload.benchmark_code,
                BenchmarkObservation.observation_date >= points[0].observation_date,
                BenchmarkObservation.observation_date <= points[-1].observation_date,
            )
        ).scalars().all()
        existing_by_date = {row.observation_date: row for row in existing_rows}

        for point in points:
            existing = existing_by_date.get(point.observation_date)
            if existing is None:
                db.add(BenchmarkObservation(
                    benchmark_code=payload.benchmark_code,
                    observation_date=point.observation_date,
                    index_value=point.index_value,
                    source_sha256=source_sha256,
                    retrieved_at=retrieved_at,
                ))
                inserted += 1
            elif Decimal(existing.index_value) != point.index_value:
                db.add(BenchmarkObservationRevision(
                    benchmark_code=payload.benchmark_code,
                    observation_date=point.observation_date,
                    previous_value=existing.index_value,
                    replacement_value=point.index_value,
                    previous_source_sha256=existing.source_sha256,
                    replacement_source_sha256=source_sha256,
                    corrected_at=retrieved_at,
                ))
                existing.index_value = point.index_value
                existing.source_sha256 = source_sha256
                existing.retrieved_at = retrieved_at
                corrected += 1
            else:
                existing.source_sha256 = source_sha256
                existing.retrieved_at = retrieved_at
                unchanged += 1

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Concurrent benchmark import conflict; retry the import") from None

    return {
        "status": "imported",
        "benchmark_code": payload.benchmark_code,
        "benchmark_name": payload.benchmark_name,
        "provider": "NSE Indices Ltd.",
        "variant": payload.variant,
        "source_url": NIFTY_HISTORICAL_DATA_URL,
        "source_sha256": source_sha256,
        "inserted_rows": inserted,
        "corrected_rows": corrected,
        "unchanged_rows": unchanged,
        **report,
    }


@app.post("/v1/benchmarks/assignments", status_code=201)
def create_scheme_benchmark_assignment(
    payload: SchemeBenchmarkAssignmentCreate,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Register a source-documented mapping; it remains pending until reviewed."""
    require_operator_api_key(x_api_key)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(Scheme, payload.scheme_code) is None:
            raise HTTPException(404, "Scheme code not found")
        benchmark = db.get(BenchmarkIndex, payload.benchmark_code)
        if benchmark is None:
            raise HTTPException(404, "Benchmark index not found")
        overlap = db.execute(
            select(SchemeBenchmarkAssignment).where(
                SchemeBenchmarkAssignment.scheme_code == payload.scheme_code,
                SchemeBenchmarkAssignment.tier == payload.tier,
                SchemeBenchmarkAssignment.valid_from <= (payload.valid_to or date.max),
                or_(
                    SchemeBenchmarkAssignment.valid_to.is_(None),
                    SchemeBenchmarkAssignment.valid_to >= payload.valid_from,
                ),
            )
        ).scalar_one_or_none()
        if overlap is not None:
            raise HTTPException(409, "An assignment already overlaps this scheme, tier and effective date range")
        assignment = SchemeBenchmarkAssignment(
            scheme_code=payload.scheme_code,
            benchmark_code=payload.benchmark_code,
            tier=payload.tier,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            source_document_url=payload.source_document_url,
            source_document_sha256=payload.source_document_sha256,
            verification_status="PENDING",
            created_at=now,
        )
        db.add(assignment)
        db.commit()
        return {
            "assignment_id": assignment.id,
            "scheme_code": assignment.scheme_code,
            "benchmark_code": assignment.benchmark_code,
            "tier": assignment.tier,
            "valid_from": assignment.valid_from.isoformat(),
            "valid_to": assignment.valid_to.isoformat() if assignment.valid_to else None,
            "verification_status": assignment.verification_status,
            "source_document_url": assignment.source_document_url,
            "source_document_sha256": assignment.source_document_sha256,
        }


@app.post("/v1/benchmarks/assignments/{assignment_id}/verify")
def verify_scheme_benchmark_assignment(
    assignment_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Mark a mapping verified only after an operator has checked its cited document."""
    require_operator_api_key(x_api_key)
    with SessionLocal() as db:
        assignment = db.get(SchemeBenchmarkAssignment, assignment_id)
        if assignment is None:
            raise HTTPException(404, "Benchmark assignment not found")
        if assignment.verification_status == "REJECTED":
            raise HTTPException(409, "A rejected benchmark assignment cannot be verified")
        assignment.verification_status = "VERIFIED"
        assignment.verified_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "assignment_id": assignment.id,
            "scheme_code": assignment.scheme_code,
            "benchmark_code": assignment.benchmark_code,
            "tier": assignment.tier,
            "verification_status": assignment.verification_status,
            "verified_at": assignment.verified_at.isoformat(),
        }


@app.get("/v1/benchmarks/assignments/{scheme_code}")
def list_scheme_benchmark_assignments(
    scheme_code: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Show effective-dated benchmark mappings and their verification evidence."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        rows = db.execute(
            select(SchemeBenchmarkAssignment, BenchmarkIndex)
            .join(BenchmarkIndex, BenchmarkIndex.benchmark_code == SchemeBenchmarkAssignment.benchmark_code)
            .where(SchemeBenchmarkAssignment.scheme_code == scheme_code)
            .order_by(SchemeBenchmarkAssignment.tier, SchemeBenchmarkAssignment.valid_from.desc())
        ).all()
        return {
            "scheme_code": scheme_code,
            "count": len(rows),
            "items": [
                {
                    "assignment_id": assignment.id,
                    "benchmark_code": benchmark.benchmark_code,
                    "benchmark_name": benchmark.benchmark_name,
                    "provider": benchmark.provider,
                    "variant": benchmark.variant,
                    "tier": assignment.tier,
                    "valid_from": assignment.valid_from.isoformat(),
                    "valid_to": assignment.valid_to.isoformat() if assignment.valid_to else None,
                    "verification_status": assignment.verification_status,
                    "verified_at": assignment.verified_at.isoformat() if assignment.verified_at else None,
                    "source_document_url": assignment.source_document_url,
                    "source_document_sha256": assignment.source_document_sha256,
                }
                for assignment, benchmark in rows
            ],
        }


@app.get("/v1/analytics/research/{scheme_code}/evidence")
def build_fund_research_evidence_pack(
    scheme_code: int,
    days: int = Query(default=3650, ge=30, le=3650),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Assemble source-linked fund facts and calculations for downstream research."""
    require_api_key(x_api_key)
    as_of = datetime.now(timezone.utc).date()
    since = as_of - timedelta(days=days)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found")
        nav_rows = db.execute(
            select(NavObservation)
            .where(
                NavObservation.scheme_code == scheme_code,
                NavObservation.nav_date >= since,
                NavObservation.nav_date <= as_of,
            )
            .order_by(NavObservation.nav_date)
        ).scalars().all()
        points = [(row.nav_date, float(row.nav_value)) for row in nav_rows]
        metrics = research_metrics(points)
        evidence = []
        sources = []
        gaps = []

        if nav_rows:
            latest = nav_rows[-1]
            ingestion = db.get(IngestionSnapshot, latest.source_snapshot_id)
            source_id = "amfi-nav-" + str(ingestion.id if ingestion else latest.source_snapshot_id)
            sources.append({
                "source_id": source_id,
                "source_type": "OFFICIAL_NAV_SOURCE",
                "title": "AMFI Net Asset Value download",
                "url": ingestion.source_url if ingestion else "https://www.amfiindia.com/net-asset-value/nav-download",
                "source_sha256": ingestion.payload_sha256 if ingestion else None,
                "retrieved_at": ingestion.retrieved_at.isoformat() if ingestion else None,
                "effective_nav_date": latest.nav_date.isoformat(),
            })
            evidence.append({
                "claim": "Latest stored scheme NAV",
                "value": str(latest.nav_value),
                "as_of_date": latest.nav_date.isoformat(),
                "source_id": source_id,
                "evidence_type": "SOURCE_FACT",
            })
            evidence.append({
                "claim": "Stored NAV observation coverage",
                "value": {
                    "observations": len(points),
                    "start_date": points[0][0].isoformat(),
                    "end_date": points[-1][0].isoformat(),
                },
                "source_id": source_id,
                "evidence_type": "SOURCE_COVERAGE",
            })
            for metric_name in ("cagr", "total_return", "annualized_volatility", "max_drawdown", "sharpe_ratio", "sortino_ratio"):
                metric_value = metrics.get(metric_name)
                if metric_value is not None:
                    evidence.append({
                        "claim": "NAV-derived " + metric_name,
                        "value": metric_value,
                        "methodology_version": metrics.get("methodology_version", "nav-research-v1"),
                        "source_id": source_id,
                        "evidence_type": "DERIVED_CALCULATION",
                    })
        else:
            gaps.append("No stored NAV observations exist in the requested period.")

        active_assignments = db.execute(
            select(SchemeBenchmarkAssignment, BenchmarkIndex)
            .join(BenchmarkIndex, BenchmarkIndex.benchmark_code == SchemeBenchmarkAssignment.benchmark_code)
            .where(
                SchemeBenchmarkAssignment.scheme_code == scheme_code,
                SchemeBenchmarkAssignment.verification_status == "VERIFIED",
                SchemeBenchmarkAssignment.valid_from <= as_of,
                or_(
                    SchemeBenchmarkAssignment.valid_to.is_(None),
                    SchemeBenchmarkAssignment.valid_to >= as_of,
                ),
            )
            .order_by(SchemeBenchmarkAssignment.tier)
        ).all()
        for assignment, benchmark in active_assignments:
            coverage = db.execute(
                select(
                    func.count(BenchmarkObservation.id),
                    func.min(BenchmarkObservation.observation_date),
                    func.max(BenchmarkObservation.observation_date),
                ).where(BenchmarkObservation.benchmark_code == benchmark.benchmark_code)
            ).one()
            source_id = "benchmark-" + benchmark.benchmark_code
            sources.append({
                "source_id": source_id,
                "source_type": "BENCHMARK_TRI_SOURCE",
                "title": benchmark.benchmark_name + " " + benchmark.variant,
                "url": benchmark.source_url,
                "first_date": coverage[1].isoformat() if coverage[1] else None,
                "last_date": coverage[2].isoformat() if coverage[2] else None,
                "observations": coverage[0],
                "mapping_source_url": assignment.source_document_url,
                "mapping_source_sha256": assignment.source_document_sha256,
                "mapping_verified_at": assignment.verified_at.isoformat() if assignment.verified_at else None,
                "tier": assignment.tier,
            })
            evidence.append({
                "claim": "Verified tier-" + str(assignment.tier) + " benchmark mapping",
                "value": {
                    "benchmark_code": benchmark.benchmark_code,
                    "benchmark_name": benchmark.benchmark_name,
                    "variant": benchmark.variant,
                    "effective_from": assignment.valid_from.isoformat(),
                    "effective_to": assignment.valid_to.isoformat() if assignment.valid_to else None,
                },
                "source_id": source_id,
                "evidence_type": "VERIFIED_MAPPING",
            })
        if not active_assignments:
            gaps.append("No verified active tier-1/tier-2 benchmark mapping is available.")

        holdings = db.execute(
            select(FundHoldingDisclosure)
            .where(
                FundHoldingDisclosure.scheme_code == scheme_code,
                FundHoldingDisclosure.verification_status == "VERIFIED",
                FundHoldingDisclosure.as_of_date <= as_of,
            )
            .order_by(desc(FundHoldingDisclosure.as_of_date), desc(FundHoldingDisclosure.retrieved_at))
            .limit(1)
        ).scalar_one_or_none()
        if holdings is not None:
            source_id = "holdings-" + str(holdings.id)
            sources.append({
                "source_id": source_id,
                "source_type": "VERIFIED_HOLDINGS_DISCLOSURE",
                "title": "Scheme portfolio disclosure as of " + holdings.as_of_date.isoformat(),
                "url": holdings.source_document_url,
                "source_sha256": holdings.source_sha256,
                "as_of_date": holdings.as_of_date.isoformat(),
                "verified_at": holdings.verified_at.isoformat() if holdings.verified_at else None,
                "row_count": holdings.row_count,
            })
            evidence.append({
                "claim": "Verified scheme holdings disclosure",
                "value": {
                    "as_of_date": holdings.as_of_date.isoformat(),
                    "row_count": holdings.row_count,
                    "total_weight_pct": str(holdings.total_weight_pct),
                },
                "source_id": source_id,
                "evidence_type": "VERIFIED_SOURCE_FACT",
            })
        else:
            gaps.append("No verified holdings disclosure is available.")

        return {
            "scheme": {
                "scheme_code": scheme.scheme_code,
                "scheme_name": scheme.scheme_name,
                "amc": scheme.amc,
                **_scheme_taxonomy(scheme),
                "plan_type": scheme.plan_type,
                "option_type": scheme.option_type,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_days": days,
            "generation_status": "EVIDENCE_ONLY_NO_LLM_GENERATION",
            "evidence": evidence,
            "sources": sources,
            "data_gaps": gaps,
            "guardrails": [
                "Do not state a fact unless it is present in evidence or a cited source.",
                "Derived metrics are NAV-only and must retain their methodology and date coverage.",
                "No benchmark claim is valid without a VERIFIED effective-dated assignment and TRI/NTR source.",
                "No holdings claim is valid without a VERIFIED dated disclosure.",
                "Do not invent AUM, TER, manager, category, benchmark or tax facts.",
            ],
        }


@app.get("/v1/analytics/research/{scheme_code}/benchmark")
def compare_fund_with_benchmark(
    scheme_code: int,
    days: int = Query(default=3650, ge=30, le=3650),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Compare fund NAV with its verified effective-dated benchmark TRI assignments."""
    require_api_key(x_api_key)
    as_of = datetime.now(timezone.utc).date()
    since = as_of - timedelta(days=days)
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found")
        assignments = db.execute(
            select(SchemeBenchmarkAssignment, BenchmarkIndex)
            .join(BenchmarkIndex, BenchmarkIndex.benchmark_code == SchemeBenchmarkAssignment.benchmark_code)
            .where(
                SchemeBenchmarkAssignment.scheme_code == scheme_code,
                SchemeBenchmarkAssignment.verification_status == "VERIFIED",
                SchemeBenchmarkAssignment.valid_from <= as_of,
                or_(
                    SchemeBenchmarkAssignment.valid_to.is_(None),
                    SchemeBenchmarkAssignment.valid_to >= as_of,
                ),
            )
            .order_by(SchemeBenchmarkAssignment.tier)
        ).all()
        if not assignments:
            return {
                "scheme_code": scheme_code,
                "scheme_name": scheme.scheme_name,
                "status": "UNMAPPED",
                "message": "No verified active benchmark mapping is available for this scheme.",
                "comparisons": [],
            }

        fund_rows = db.execute(
            select(NavObservation.nav_date, NavObservation.nav_value)
            .where(
                NavObservation.scheme_code == scheme_code,
                NavObservation.nav_date >= since,
            )
            .order_by(NavObservation.nav_date)
        ).all()
        fund_points = [(row.nav_date, float(row.nav_value)) for row in fund_rows]
        comparisons = []
        for assignment, benchmark in assignments:
            benchmark_rows = db.execute(
                select(BenchmarkObservation.observation_date, BenchmarkObservation.index_value)
                .where(
                    BenchmarkObservation.benchmark_code == benchmark.benchmark_code,
                    BenchmarkObservation.observation_date >= since,
                )
                .order_by(BenchmarkObservation.observation_date)
            ).all()
            benchmark_points = [(row.observation_date, float(row.index_value)) for row in benchmark_rows]
            metrics = benchmark_comparison_metrics(fund_points, benchmark_points)
            comparisons.append({
                "benchmark_code": benchmark.benchmark_code,
                "benchmark_name": benchmark.benchmark_name,
                "provider": benchmark.provider,
                "variant": benchmark.variant,
                "tier": assignment.tier,
                "source_document_url": assignment.source_document_url,
                "source_document_sha256": assignment.source_document_sha256,
                "metrics": metrics,
            })

        limitations = [
            "Only exact common NAV and benchmark dates are compared; no interpolation or forward-fill is used.",
            "Alpha, beta, tracking error and information ratio require at least 30 adjacent common-date return pairs no more than seven calendar days apart.",
            "Scheme benchmark mappings are effective-dated and only operator-verified mappings are used.",
        ]
        if (scheme.option_type or "").lower() not in {"growth", "reinvestment"}:
            limitations.append("This scheme option may distribute cash; NAV-only fund returns are not distribution-adjusted and should not be compared as investor total returns.")
        return {
            "scheme_code": scheme_code,
            "scheme_name": scheme.scheme_name,
            "status": "OK",
            "days_requested": days,
            "as_of_date": as_of.isoformat(),
            "comparisons": comparisons,
            "limitations": limitations,
        }


@app.post("/v1/portfolios/{portfolio_id}/reports", status_code=201)
def create_portfolio_report_snapshot(
    portfolio_id: int,
    days: int = Query(default=1095, ge=30, le=3650),
) -> dict[str, Any]:
    """Generate and persist an immutable owner-scoped portfolio report snapshot."""
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        _require_portfolio_owner(db, portfolio_id)

    # Reuse the same tested valuation, risk and FIFO calculation endpoints.
    valuation = portfolio_valuation(portfolio_id, None)
    risk = portfolio_historical_risk(portfolio_id, days, None)
    tax_lots = portfolio_fifo_tax_lots(portfolio_id, None)
    lookthrough = portfolio_holdings_lookthrough(portfolio_id, 180)
    generated_at = datetime.now(timezone.utc)

    with SessionLocal() as db:
        portfolio = _require_portfolio_owner(db, portfolio_id)
        holdings = valuation.get("holdings", [])
        current_value = float(valuation.get("current_value") or 0)
        for holding in holdings:
            holding["weight_pct"] = (
                round(float(holding["market_value"]) / current_value * 100, 4)
                if current_value > 0 and holding.get("market_value") is not None else None
            )
            holding["freshness_status"] = holding.get("nav_freshness")
        source_snapshot_ids = set()
        max_nav_date = None
        for holding in holdings:
            code = holding.get("scheme_code")
            nav_date = holding.get("nav_date")
            if nav_date:
                parsed_date = date.fromisoformat(nav_date)
                max_nav_date = parsed_date if max_nav_date is None else max(max_nav_date, parsed_date)
            if code:
                latest = db.execute(
                    select(NavObservation)
                    .where(NavObservation.scheme_code == code)
                    .order_by(desc(NavObservation.nav_date))
                    .limit(1)
                ).scalar_one_or_none()
                if latest is not None:
                    source_snapshot_ids.add(latest.source_snapshot_id)

        sources = []
        for snapshot_id in sorted(source_snapshot_ids):
            snapshot = db.get(IngestionSnapshot, snapshot_id)
            if snapshot is not None:
                sources.append({
                    "source_type": "AMFI_NAV_INGESTION",
                    "source_url": snapshot.source_url,
                    "source_sha256": snapshot.payload_sha256,
                    "retrieved_at": snapshot.retrieved_at.isoformat(),
                    "min_nav_date": snapshot.min_nav_date.isoformat() if snapshot.min_nav_date else None,
                    "max_nav_date": snapshot.max_nav_date.isoformat() if snapshot.max_nav_date else None,
                    "quality_status": snapshot.quality_status,
                })

        for source in lookthrough.get("sources", []):
            sources.append({
                "source_type": "VERIFIED_HOLDINGS_DISCLOSURE",
                "title": source.get("scheme_name"),
                "url": source.get("source_document_url"),
                "source_sha256": source.get("source_sha256"),
                "as_of_date": source.get("as_of_date"),
                "disclosure_id": source.get("disclosure_id"),
                "freshness": source.get("freshness"),
            })

        limitations = [
            "Historical risk uses current market-value weights held constant over the lookback.",
            "FIFO gains are pre-tax; no Indian tax rates, surcharge, cess, exemption or exit load is applied.",
            "Portfolio-level benchmark TRI attribution is not included until every holding has a verified effective-dated benchmark mapping.",
            "No future returns or goal achievement are guaranteed.",
            "Look-through coverage status: " + str(lookthrough.get("coverage", {}).get("status")),
        ]
        if risk.get("status") != "OK":
            limitations.append("Portfolio risk metrics are unavailable or incomplete: " + str(risk.get("status")))
        if valuation.get("valuation_status") != "COMPLETE":
            limitations.append("Portfolio valuation has a data-quality status: " + str(valuation.get("valuation_status")))

        report = {
            "report_version": "portfolio-report-v1",
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "generated_at": generated_at.isoformat(),
            "lookback_days": days,
            "valuation": valuation,
            "risk": risk,
            "lookthrough": lookthrough,
            "fifo_tax_lots": tax_lots,
            "sources": sources,
            "source_max_nav_date": max_nav_date.isoformat() if max_nav_date else None,
            "limitations": limitations,
            "methodology": {
                "valuation": "Latest accepted AMFI NAV multiplied by remaining units.",
                "risk": "Exact common NAV dates; no forward-fill; current weights held constant.",
                "capital_gains": "FIFO lot matching with recorded charges; pre-tax only.",
            },
        }
        content_json = json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True)
        content_sha256 = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        snapshot = PortfolioReportSnapshot(
            portfolio_id=portfolio_id,
            owner_user_id=owner_id,
            generated_at=generated_at,
            report_version="portfolio-report-v1",
            content_json=content_json,
            content_sha256=content_sha256,
            source_max_nav_date=max_nav_date,
        )
        db.add(snapshot)
        db.commit()
        return {
            "report_id": snapshot.id,
            "portfolio_id": portfolio_id,
            "report_version": snapshot.report_version,
            "generated_at": snapshot.generated_at.isoformat(),
            "source_max_nav_date": snapshot.source_max_nav_date.isoformat() if snapshot.source_max_nav_date else None,
            "content_sha256": snapshot.content_sha256,
            "status": "saved",
        }


@app.get("/v1/portfolios/{portfolio_id}/reports")
def list_portfolio_report_snapshots(portfolio_id: int) -> dict[str, Any]:
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        _require_portfolio_owner(db, portfolio_id)
        rows = db.execute(
            select(PortfolioReportSnapshot)
            .where(
                PortfolioReportSnapshot.portfolio_id == portfolio_id,
                PortfolioReportSnapshot.owner_user_id == owner_id,
            )
            .order_by(desc(PortfolioReportSnapshot.generated_at))
        ).scalars().all()
        return {
            "count": len(rows),
            "items": [
                {
                    "report_id": row.id,
                    "report_version": row.report_version,
                    "generated_at": row.generated_at.isoformat(),
                    "source_max_nav_date": row.source_max_nav_date.isoformat() if row.source_max_nav_date else None,
                    "content_sha256": row.content_sha256,
                }
                for row in rows
            ],
        }


@app.get("/v1/reports/{report_id}")
def get_portfolio_report_snapshot(report_id: int) -> dict[str, Any]:
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        row = db.execute(
            select(PortfolioReportSnapshot).where(
                PortfolioReportSnapshot.id == report_id,
                PortfolioReportSnapshot.owner_user_id == owner_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "Report not found")
        return {
            "report_id": row.id,
            "report_version": row.report_version,
            "generated_at": row.generated_at.isoformat(),
            "content_sha256": row.content_sha256,
            "integrity_status": (
                "VERIFIED"
                if hashlib.sha256(row.content_json.encode("utf-8")).hexdigest() == row.content_sha256
                else "HASH_MISMATCH"
            ),
            "report": json.loads(row.content_json),
        }


@app.get("/v1/reports/{report_id}/pdf")
def download_portfolio_report_pdf(report_id: int) -> Response:
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        row = db.execute(
            select(PortfolioReportSnapshot).where(
                PortfolioReportSnapshot.id == report_id,
                PortfolioReportSnapshot.owner_user_id == owner_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "Report not found")
        report = json.loads(row.content_json)
    pdf_bytes = build_portfolio_report_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="portfolio-report-{report_id}.pdf"'},
    )


@app.get("/v1/goals")
def list_portfolio_goals() -> dict[str, Any]:
    """List only goals owned by the verified Supabase user."""
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        goals = db.execute(
            select(PortfolioGoal)
            .where(PortfolioGoal.owner_user_id == owner_id)
            .order_by(PortfolioGoal.target_date, PortfolioGoal.id)
        ).scalars().all()
        return {
            "count": len(goals),
            "items": [
                {
                    "id": goal.id,
                    "name": goal.name,
                    "target_amount_today": str(goal.target_amount_today),
                    "target_date": goal.target_date.isoformat(),
                    "current_amount": str(goal.current_amount),
                    "linked_portfolio_id": goal.linked_portfolio_id,
                    "monthly_contribution": str(goal.monthly_contribution),
                    "inflation_rate": goal.inflation_rate,
                    "annual_return_low": goal.annual_return_low,
                    "annual_return_base": goal.annual_return_base,
                    "annual_return_high": goal.annual_return_high,
                    "created_at": goal.created_at.isoformat(),
                    "updated_at": goal.updated_at.isoformat(),
                }
                for goal in goals
            ],
        }


@app.post("/v1/goals", status_code=201)
def create_portfolio_goal(payload: GoalCreateRequest) -> dict[str, Any]:
    """Create a private financial goal with explicitly user-supplied assumptions."""
    owner_id = require_authenticated_user()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if payload.linked_portfolio_id is not None:
            _require_portfolio_owner(db, payload.linked_portfolio_id)
        goal = PortfolioGoal(
            owner_user_id=owner_id,
            linked_portfolio_id=payload.linked_portfolio_id,
            name=payload.name,
            target_amount_today=payload.target_amount_today,
            target_date=payload.target_date,
            current_amount=payload.current_amount,
            monthly_contribution=payload.monthly_contribution,
            inflation_rate=payload.inflation_rate,
            annual_return_low=payload.annual_return_low,
            annual_return_base=payload.annual_return_base,
            annual_return_high=payload.annual_return_high,
            created_at=now,
            updated_at=now,
        )
        db.add(goal)
        db.commit()
        return {"id": goal.id, "status": "created", "owner_scope": "private"}


@app.put("/v1/goals/{goal_id}")
def update_portfolio_goal(goal_id: int, payload: GoalCreateRequest) -> dict[str, Any]:
    """Replace a goal's assumptions only for the authenticated owner."""
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        goal = db.execute(
            select(PortfolioGoal).where(
                PortfolioGoal.id == goal_id,
                PortfolioGoal.owner_user_id == owner_id,
            )
        ).scalar_one_or_none()
        if goal is None:
            raise HTTPException(404, "Goal not found")
        if payload.linked_portfolio_id is not None:
            _require_portfolio_owner(db, payload.linked_portfolio_id)
        goal.linked_portfolio_id = payload.linked_portfolio_id
        goal.name = payload.name
        goal.target_amount_today = payload.target_amount_today
        goal.target_date = payload.target_date
        goal.current_amount = payload.current_amount
        goal.monthly_contribution = payload.monthly_contribution
        goal.inflation_rate = payload.inflation_rate
        goal.annual_return_low = payload.annual_return_low
        goal.annual_return_base = payload.annual_return_base
        goal.annual_return_high = payload.annual_return_high
        goal.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"id": goal.id, "status": "updated"}


@app.delete("/v1/goals/{goal_id}")
def delete_portfolio_goal(goal_id: int) -> dict[str, Any]:
    """Delete only the authenticated owner's goal."""
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        goal = db.execute(
            select(PortfolioGoal).where(
                PortfolioGoal.id == goal_id,
                PortfolioGoal.owner_user_id == owner_id,
            )
        ).scalar_one_or_none()
        if goal is None:
            raise HTTPException(404, "Goal not found")
        db.delete(goal)
        db.commit()
        return {"id": goal_id, "status": "deleted"}


@app.get("/v1/goals/{goal_id}/projection")
def project_portfolio_goal(goal_id: int) -> dict[str, Any]:
    """Return low/base/high goal scenarios without implying guaranteed returns."""
    owner_id = require_authenticated_user()
    with SessionLocal() as db:
        goal = db.execute(
            select(PortfolioGoal).where(
                PortfolioGoal.id == goal_id,
                PortfolioGoal.owner_user_id == owner_id,
            )
        ).scalar_one_or_none()
        if goal is None:
            raise HTTPException(404, "Goal not found")
        today = datetime.now(timezone.utc).date()
        months = max(
            0,
            (goal.target_date.year - today.year) * 12
            + goal.target_date.month - today.month
            - (1 if goal.target_date.day < today.day else 0),
        )
        current_amount = float(goal.current_amount)
        linked_portfolio = None
        if goal.linked_portfolio_id is not None:
            valuation = portfolio_valuation(goal.linked_portfolio_id, None)
            if valuation.get("valuation_status") != "COMPLETE":
                raise HTTPException(
                    409,
                    "Linked portfolio valuation is incomplete; resolve missing NAV coverage before using it for goal progress.",
                )
            if valuation.get("valuation_freshness") != "FRESH":
                raise HTTPException(
                    409,
                    "Linked portfolio NAV is stale; refresh NAV data before using it for goal progress.",
                )
            current_amount = float(valuation["current_value"])
            linked_portfolio = {
                "portfolio_id": goal.linked_portfolio_id,
                "portfolio_name": valuation["portfolio_name"],
                "market_value": current_amount,
                "valuation_date": valuation.get("valuation_date"),
                "valuation_freshness": valuation.get("valuation_freshness"),
            }
        projection = project_financial_goal(
            target_amount_today=float(goal.target_amount_today),
            current_amount=current_amount,
            monthly_contribution=float(goal.monthly_contribution),
            months=months,
            inflation_rate=goal.inflation_rate,
            annual_return_scenarios={
                "low": goal.annual_return_low,
                "base": goal.annual_return_base,
                "high": goal.annual_return_high,
            },
        )
        return {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "target_date": goal.target_date.isoformat(),
            "currency": "INR",
            "linked_portfolio": linked_portfolio,
            "current_amount_source": "LINKED_PORTFOLIO_MARKET_VALUE" if linked_portfolio else "USER_ENTERED",
            "projection": projection,
            "limitations": [
                "Return and inflation rates are user-entered assumptions, not forecasts or guarantees.",
                "Taxes, fund expenses, exit loads and contribution interruptions are not included.",
                "This projection is not a personalised investment recommendation.",
            ],
        }


@app.post("/v1/holdings/import-csv")
def import_fund_holdings_csv(
    payload: HoldingsImportRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Import one dated AMC/AMFI holdings disclosure as an immutable source snapshot."""
    require_operator_api_key(x_api_key)
    source_sha256 = hashlib.sha256(payload.csv_text.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(source_sha256, payload.source_document_sha256):
        raise HTTPException(422, "source_document_sha256 must match the exact uploaded CSV text")
    try:
        points, report = parse_fund_holdings_csv(payload.csv_text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    retrieved_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(Scheme, payload.scheme_code) is None:
            raise HTTPException(404, "Scheme code not found")
        existing = db.execute(
            select(FundHoldingDisclosure).where(
                FundHoldingDisclosure.scheme_code == payload.scheme_code,
                FundHoldingDisclosure.as_of_date == payload.as_of_date,
                FundHoldingDisclosure.source_sha256 == source_sha256,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "status": "already_imported",
                "verification_status": existing.verification_status,
                "disclosure_id": existing.id,
                "scheme_code": existing.scheme_code,
                "as_of_date": existing.as_of_date.isoformat(),
                "row_count": existing.row_count,
                "source_sha256": existing.source_sha256,
                **report,
            }

        supersedes = db.execute(
            select(FundHoldingDisclosure)
            .where(
                FundHoldingDisclosure.scheme_code == payload.scheme_code,
                FundHoldingDisclosure.as_of_date == payload.as_of_date,
            )
            .order_by(desc(FundHoldingDisclosure.retrieved_at), desc(FundHoldingDisclosure.id))
            .limit(1)
        ).scalar_one_or_none()
        disclosure = FundHoldingDisclosure(
            scheme_code=payload.scheme_code,
            as_of_date=payload.as_of_date,
            source_document_url=payload.source_document_url,
            source_sha256=source_sha256,
            retrieved_at=retrieved_at,
            row_count=len(points),
            total_weight_pct=Decimal(report["total_weight_pct"]),
            verification_status="PENDING",
            supersedes_disclosure_id=supersedes.id if supersedes else None,
        )
        db.add(disclosure)
        db.flush()
        db.add_all([
            FundHolding(
                disclosure_id=disclosure.id,
                security_id=point.security_id,
                security_name=point.security_name,
                is_isin=point.is_isin,
                asset_type=point.asset_type,
                sector=point.sector,
                weight_pct=point.weight_pct,
                market_value_inr=point.market_value_inr,
            )
            for point in points
        ])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Concurrent holdings import conflict; retry the import") from None

        return {
            "status": "imported",
            "verification_status": disclosure.verification_status,
            "disclosure_id": disclosure.id,
            "scheme_code": disclosure.scheme_code,
            "as_of_date": disclosure.as_of_date.isoformat(),
            "source_document_url": disclosure.source_document_url,
            "source_sha256": disclosure.source_sha256,
            "supersedes_disclosure_id": disclosure.supersedes_disclosure_id,
            "row_count": disclosure.row_count,
            **report,
        }


@app.post("/v1/holdings/disclosures/{disclosure_id}/verify")
def verify_fund_holdings_disclosure(
    disclosure_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Approve a disclosure only after an operator checks the linked official source file."""
    require_operator_api_key(x_api_key)
    with SessionLocal() as db:
        disclosure = db.get(FundHoldingDisclosure, disclosure_id)
        if disclosure is None:
            raise HTTPException(404, "Holdings disclosure not found")
        if disclosure.verification_status == "REJECTED":
            raise HTTPException(409, "A rejected holdings disclosure cannot be verified")
        disclosure.verification_status = "VERIFIED"
        disclosure.verified_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "disclosure_id": disclosure.id,
            "scheme_code": disclosure.scheme_code,
            "as_of_date": disclosure.as_of_date.isoformat(),
            "verification_status": disclosure.verification_status,
            "verified_at": disclosure.verified_at.isoformat(),
            "source_document_url": disclosure.source_document_url,
            "source_sha256": disclosure.source_sha256,
        }


@app.get("/v1/holdings/{scheme_code}")
def get_fund_holdings(
    scheme_code: int,
    as_of_date: date | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Return the latest accepted holdings disclosure on or before the requested date."""
    require_api_key(x_api_key)
    cutoff = as_of_date or datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        scheme = db.get(Scheme, scheme_code)
        if scheme is None:
            raise HTTPException(404, "Scheme code not found")
        disclosure = db.execute(
            select(FundHoldingDisclosure)
            .where(
                FundHoldingDisclosure.scheme_code == scheme_code,
                FundHoldingDisclosure.as_of_date <= cutoff,
                FundHoldingDisclosure.verification_status == "VERIFIED",
            )
            .order_by(desc(FundHoldingDisclosure.as_of_date), desc(FundHoldingDisclosure.retrieved_at))
            .limit(1)
        ).scalar_one_or_none()
        if disclosure is None:
            raise HTTPException(404, "No holdings disclosure is available for this scheme")
        rows = db.execute(
            select(FundHolding).where(FundHolding.disclosure_id == disclosure.id)
            .order_by(desc(FundHolding.weight_pct), FundHolding.security_name)
        ).scalars().all()
        return {
            "scheme_code": scheme_code,
            "scheme_name": scheme.scheme_name,
            "disclosure_id": disclosure.id,
            "verification_status": disclosure.verification_status,
            "verified_at": disclosure.verified_at.isoformat() if disclosure.verified_at else None,
            "as_of_date": disclosure.as_of_date.isoformat(),
            "retrieved_at": disclosure.retrieved_at.isoformat(),
            "source_document_url": disclosure.source_document_url,
            "source_sha256": disclosure.source_sha256,
            "supersedes_disclosure_id": disclosure.supersedes_disclosure_id,
            "row_count": disclosure.row_count,
            "total_weight_pct": str(disclosure.total_weight_pct),
            "items": [
                {
                    "security_id": row.security_id,
                    "security_name": row.security_name,
                    "is_isin": row.is_isin,
                    "asset_type": row.asset_type,
                    "sector": row.sector,
                    "weight_pct": str(row.weight_pct),
                    "market_value_inr": str(row.market_value_inr) if row.market_value_inr is not None else None,
                }
                for row in rows
            ],
        }


@app.get("/v1/analytics/holdings-overlap")
def compare_fund_holdings_overlap(
    scheme_a: int = Query(gt=0),
    scheme_b: int = Query(gt=0),
    as_of_date: date | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Calculate transparent, symmetric overlap using positive matched ISIN weights."""
    require_api_key(x_api_key)
    if scheme_a == scheme_b:
        raise HTTPException(422, "Choose two different scheme codes")
    cutoff = as_of_date or datetime.now(timezone.utc).date()

    with SessionLocal() as db:
        schemes = {
            scheme.scheme_code: scheme
            for scheme in db.execute(
                select(Scheme).where(Scheme.scheme_code.in_([scheme_a, scheme_b]))
            ).scalars().all()
        }
        if len(schemes) != 2:
            raise HTTPException(404, "One or both scheme codes were not found")

        disclosures = {}
        for code in (scheme_a, scheme_b):
            disclosure = db.execute(
                select(FundHoldingDisclosure)
                .where(
                    FundHoldingDisclosure.scheme_code == code,
                    FundHoldingDisclosure.as_of_date <= cutoff,
                    FundHoldingDisclosure.verification_status == "VERIFIED",
                )
                .order_by(desc(FundHoldingDisclosure.as_of_date), desc(FundHoldingDisclosure.retrieved_at))
                .limit(1)
            ).scalar_one_or_none()
            if disclosure is None:
                raise HTTPException(409, f"No holdings disclosure is available for scheme {code}")
            disclosures[code] = disclosure

        holdings_by_scheme: dict[int, dict[str, FundHolding]] = {}
        coverage = {}
        for code, disclosure in disclosures.items():
            rows = db.execute(
                select(FundHolding).where(FundHolding.disclosure_id == disclosure.id)
            ).scalars().all()
            all_positive = sum((row.weight_pct for row in rows if row.weight_pct > 0), Decimal("0"))
            isin_rows = {
                row.security_id: row
                for row in rows
                if row.is_isin and row.weight_pct > 0
            }
            isin_positive = sum((row.weight_pct for row in isin_rows.values()), Decimal("0"))
            holdings_by_scheme[code] = isin_rows
            coverage[code] = {
                "total_positive_weight_pct": all_positive,
                "isin_matched_weight_pct": isin_positive,
                "isin_coverage_pct": (isin_positive / all_positive * 100) if all_positive > 0 else None,
            }

        left = holdings_by_scheme[scheme_a]
        right = holdings_by_scheme[scheme_b]
        common_ids = set(left).intersection(right)
        shared = []
        overlap_weight = Decimal("0")
        shared_a = Decimal("0")
        shared_b = Decimal("0")
        for security_id in common_ids:
            weight_a = left[security_id].weight_pct
            weight_b = right[security_id].weight_pct
            matched_weight = min(weight_a, weight_b)
            overlap_weight += matched_weight
            shared_a += weight_a
            shared_b += weight_b
            shared.append({
                "isin": security_id,
                "security_name": left[security_id].security_name,
                "weight_in_scheme_a_pct": str(weight_a),
                "weight_in_scheme_b_pct": str(weight_b),
                "matched_overlap_weight_pct": str(matched_weight),
            })
        shared.sort(key=lambda item: Decimal(item["matched_overlap_weight_pct"]), reverse=True)

        age_a = (cutoff - disclosures[scheme_a].as_of_date).days
        age_b = (cutoff - disclosures[scheme_b].as_of_date).days
        stale = age_a > 90 or age_b > 90
        return {
            "status": "STALE_DISCLOSURE" if stale else "OK",
            "scheme_a": {
                "scheme_code": scheme_a,
                "scheme_name": schemes[scheme_a].scheme_name,
                "as_of_date": disclosures[scheme_a].as_of_date.isoformat(),
                "disclosure_age_days": age_a,
                "source_document_url": disclosures[scheme_a].source_document_url,
                "source_sha256": disclosures[scheme_a].source_sha256,
                "coverage": {key: str(value) if value is not None else None for key, value in coverage[scheme_a].items()},
            },
            "scheme_b": {
                "scheme_code": scheme_b,
                "scheme_name": schemes[scheme_b].scheme_name,
                "as_of_date": disclosures[scheme_b].as_of_date.isoformat(),
                "disclosure_age_days": age_b,
                "source_document_url": disclosures[scheme_b].source_document_url,
                "source_sha256": disclosures[scheme_b].source_sha256,
                "coverage": {key: str(value) if value is not None else None for key, value in coverage[scheme_b].items()},
            },
            "common_isin_count": len(common_ids),
            "holdings_overlap_pct": str(overlap_weight),
            "shared_weight_in_scheme_a_pct": str(shared_a),
            "shared_weight_in_scheme_b_pct": str(shared_b),
            "top_shared_holdings": shared[:20],
            "methodology": (
                "For each common ISIN, overlap contribution is the lower of the two positive "
                "weights (% of each scheme's net assets); total overlap is the sum of those "
                "contributions. Non-ISIN rows and negative exposures are excluded. No fuzzy "
                "security-name matching is used."
            ),
            "limitations": [
                "Disclosure dates may differ between schemes; the response shows each as-of date and age.",
                "Coverage is the positive portfolio weight represented by valid ISIN rows divided by total positive reported weight.",
                "Overlap is a holdings snapshot, not a forecast of future correlation or portfolio risk.",
            ],
        }


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
    user_id = _authenticated_user_id.get()
    if user_id and portfolio.owner_user_id != user_id:
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
    owner_user_id = _authenticated_user_id.get()
    if not owner_user_id and os.getenv("ENVIRONMENT", "").lower() == "production":
        owner_user_id = require_authenticated_user()
    with SessionLocal() as db:
        portfolio = Portfolio(name=payload.name.strip(), currency=payload.currency, owner_user_id=owner_user_id or "legacy-operator", created_at=datetime.now(timezone.utc))
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        return {"id": portfolio.id, "name": portfolio.name, "currency": portfolio.currency, "created_at": portfolio.created_at.isoformat()}


@app.get("/v1/portfolios")
def list_portfolios(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    require_api_key(x_api_key)
    user_id = _authenticated_user_id.get()
    if not user_id and os.getenv("ENVIRONMENT", "").lower() == "production":
        user_id = require_authenticated_user()
    with SessionLocal() as db:
        portfolio_query = select(Portfolio).order_by(Portfolio.created_at.desc())
        if user_id:
            portfolio_query = portfolio_query.where(Portfolio.owner_user_id == user_id)
        rows = db.execute(portfolio_query).scalars().all()
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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
        _require_portfolio_owner(db, portfolio_id)
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


@app.get("/v1/portfolios/{portfolio_id}/lookthrough")
def portfolio_holdings_lookthrough(
    portfolio_id: int,
    max_disclosure_age_days: int = Query(default=180, ge=30, le=730),
) -> dict[str, Any]:
    """Aggregate verified constituent and sector exposures across owned fund holdings."""
    require_authenticated_user()
    valuation = portfolio_valuation(portfolio_id, None)
    as_of = datetime.now(timezone.utc).date()
    total_value = Decimal(str(valuation.get("current_value") or "0"))
    valuation_complete = valuation.get("valuation_status") == "COMPLETE"
    security_totals: dict[str, dict[str, Any]] = {}
    sector_totals: dict[str, Decimal] = {}
    source_rows = []
    missing_codes = []
    stale_codes = []
    covered_value = Decimal("0")
    fresh_covered_value = Decimal("0")
    stale_covered_value = Decimal("0")
    holdings_with_value = [
        item for item in valuation.get("holdings", [])
        if item.get("market_value") is not None and Decimal(str(item.get("market_value"))) > 0
    ]

    with SessionLocal() as db:
        _require_portfolio_owner(db, portfolio_id)
        for holding in holdings_with_value:
            scheme_code = int(holding["scheme_code"])
            market_value = Decimal(str(holding["market_value"]))
            disclosure = db.execute(
                select(FundHoldingDisclosure)
                .where(
                    FundHoldingDisclosure.scheme_code == scheme_code,
                    FundHoldingDisclosure.verification_status == "VERIFIED",
                    FundHoldingDisclosure.as_of_date <= as_of,
                )
                .order_by(
                    desc(FundHoldingDisclosure.as_of_date),
                    desc(FundHoldingDisclosure.retrieved_at),
                    desc(FundHoldingDisclosure.id),
                )
                .limit(1)
            ).scalar_one_or_none()
            if disclosure is None:
                missing_codes.append(scheme_code)
                continue

            age_days = (as_of - disclosure.as_of_date).days
            is_stale = age_days > max_disclosure_age_days
            if is_stale:
                stale_codes.append(scheme_code)
                stale_covered_value += market_value
            else:
                fresh_covered_value += market_value
            covered_value += market_value

            source_rows.append({
                "scheme_code": scheme_code,
                "scheme_name": holding["scheme_name"],
                "disclosure_id": disclosure.id,
                "as_of_date": disclosure.as_of_date.isoformat(),
                "age_days": age_days,
                "freshness": "STALE" if is_stale else "FRESH",
                "source_document_url": disclosure.source_document_url,
                "source_sha256": disclosure.source_sha256,
                "row_count": disclosure.row_count,
            })

            rows = db.execute(
                select(FundHolding).where(FundHolding.disclosure_id == disclosure.id)
            ).scalars().all()
            for row in rows:
                exposure = market_value * Decimal(row.weight_pct) / Decimal("100")
                # Only ISINs are stable cross-fund identifiers. Name-derived
                # fallback IDs are disclosure-local to avoid false issuer matches.
                security_key = (
                    ("ISIN:" + row.security_id.upper())
                    if row.is_isin
                    else ("NONISIN:" + str(disclosure.id) + ":" + row.security_id.upper())
                )
                aggregate = security_totals.setdefault(
                    security_key,
                    {
                        "security_id": row.security_id,
                        "security_name": row.security_name,
                        "is_isin": row.is_isin,
                        "identity_basis": "ISIN" if row.is_isin else "DISCLOSURE_LOCAL_NAME_KEY",
                        "asset_type": row.asset_type,
                        "sector": row.sector or "Unclassified",
                        "lookthrough_value": Decimal("0"),
                        "fresh_lookthrough_value": Decimal("0"),
                        "stale_lookthrough_value": Decimal("0"),
                        "scheme_codes": set(),
                        "source_disclosure_ids": set(),
                    },
                )
                aggregate["lookthrough_value"] += exposure
                aggregate["stale_lookthrough_value" if is_stale else "fresh_lookthrough_value"] += exposure
                aggregate["scheme_codes"].add(scheme_code)
                aggregate["source_disclosure_ids"].add(disclosure.id)
                sector_key = row.sector or "Unclassified"
                sector_totals[sector_key] = sector_totals.get(sector_key, Decimal("0")) + exposure

    security_rows = []
    for item in security_totals.values():
        exposure_value = item["lookthrough_value"]
        security_rows.append({
            "security_id": item["security_id"],
            "security_name": item["security_name"],
            "is_isin": item["is_isin"],
            "identity_basis": item["identity_basis"],
            "asset_type": item["asset_type"],
            "sector": item["sector"],
            "lookthrough_value": str(exposure_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "fresh_disclosure_exposure_inr": str(item["fresh_lookthrough_value"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "stale_disclosure_exposure_inr": str(item["stale_lookthrough_value"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "portfolio_weight_pct": (
                float((exposure_value / total_value * 100).quantize(Decimal("0.0001")))
                if valuation_complete and total_value > 0 else None
            ),
            "scheme_count": len(item["scheme_codes"]),
            "scheme_codes": sorted(item["scheme_codes"]),
            "source_disclosure_ids": sorted(item["source_disclosure_ids"]),
        })
    security_rows.sort(
        key=lambda item: (Decimal(item["lookthrough_value"]), item["security_name"].casefold()),
        reverse=True,
    )

    sector_rows = []
    for sector, exposure_value in sector_totals.items():
        sector_rows.append({
            "sector": sector,
            "lookthrough_value": str(exposure_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "portfolio_weight_pct": (
                float((exposure_value / total_value * 100).quantize(Decimal("0.0001")))
                if valuation_complete and total_value > 0 else None
            ),
        })
    sector_rows.sort(key=lambda item: Decimal(item["lookthrough_value"]), reverse=True)
    concentration = security_concentration_metrics(
        security_rows,
        portfolio_value=total_value,
        valuation_complete=valuation_complete,
    )

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": valuation["portfolio_name"],
        "as_of_date": as_of.isoformat(),
        "valuation_date": valuation.get("valuation_date"),
        "valuation_status": valuation.get("valuation_status"),
        "valuation_freshness": valuation.get("valuation_freshness"),
        "portfolio_value": str(total_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "disclosure_max_age_days": max_disclosure_age_days,
        "coverage": {
            "status": (
                "INCOMPLETE_PORTFOLIO_VALUATION" if not valuation_complete
                else "PARTIAL_MISSING_DISCLOSURES" if missing_codes
                else "PARTIAL_STALE_DISCLOSURES" if stale_codes
                else "COMPLETE"
            ),
            "covered_market_value": str(covered_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "fresh_covered_market_value": str(fresh_covered_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "stale_covered_market_value": str(stale_covered_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "missing_disclosure_scheme_codes": sorted(missing_codes),
            "missing_nav_scheme_codes": sorted(valuation.get("missing_nav_scheme_codes", [])),
            "stale_nav_scheme_codes": sorted(valuation.get("stale_nav_scheme_codes", [])),
            "stale_disclosure_scheme_codes": sorted(stale_codes),
            "covered_weight_pct": (
                float((covered_value / total_value * 100).quantize(Decimal("0.0001")))
                if valuation_complete and total_value > 0 else None
            ),
            "fresh_covered_weight_pct": (
                float((fresh_covered_value / total_value * 100).quantize(Decimal("0.0001")))
                if valuation_complete and total_value > 0 else None
            ),
        },
        "top_securities": security_rows[:50],
        "sector_exposure": sector_rows,
        "security_concentration": concentration,
        "sources": source_rows,
        "methodology": (
            "Current scheme market value is multiplied by the constituent weight in the latest "
            "VERIFIED disclosure on or before the as-of date. Same securities are aggregated by "
            "ISIN where available; non-ISIN rows remain disclosure-local because normalized names "
            "are not reliable cross-fund security identifiers. "
            "No holdings are inferred for missing disclosures. Stale disclosures are included "
            "but explicitly separated from fresh coverage."
        ),
        "limitations": [
            "This is a disclosure look-through, not live underlying security valuation.",
            "Fund portfolio weights may not total 100% because of cash, derivatives, rounding or disclosure conventions.",
            "Unverified disclosures are never used.",
            "Portfolio weight percentages are withheld when portfolio NAV valuation is incomplete.",
            "Security names and sector classifications are source-reported and may differ across AMCs.",
        ],
    }


@app.get("/v1/portfolios/{portfolio_id}/tax-lots")
def portfolio_fifo_tax_lots(
    portfolio_id: int,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Return FIFO acquisition/redemption lots without applying unverified tax rates."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        portfolio = _require_portfolio_owner(db, portfolio_id)
        transactions = db.execute(
            select(PortfolioTransaction)
            .where(
                PortfolioTransaction.portfolio_id == portfolio_id,
                PortfolioTransaction.voided_at.is_(None),
            )
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        latest_nav_by_scheme: dict[int, Decimal] = {}
        scheme_metadata = {}
        transaction_rows = []
        for transaction in transactions:
            transaction_rows.append({
                "id": transaction.id,
                "scheme_code": transaction.scheme_code,
                "transaction_type": transaction.transaction_type,
                "transaction_date": transaction.transaction_date,
                "units": transaction.units,
                "amount": transaction.amount,
                "charges": transaction.charges,
            })
            if transaction.scheme_code not in scheme_metadata:
                scheme = db.get(Scheme, transaction.scheme_code)
                scheme_metadata[transaction.scheme_code] = {
                    "scheme_name": scheme.scheme_name if scheme else str(transaction.scheme_code),
                    **(_scheme_taxonomy(scheme) if scheme else {"category_group": None, "category": None, "asset_class": None}),
                    "tax_rule_status": "UNVERIFIED_SCHEME_TAX_CLASSIFICATION",
                }
                latest = db.execute(
                    select(NavObservation)
                    .where(NavObservation.scheme_code == transaction.scheme_code)
                    .order_by(desc(NavObservation.nav_date))
                    .limit(1)
                ).scalar_one_or_none()
                if latest is not None:
                    latest_nav_by_scheme[transaction.scheme_code] = Decimal(latest.nav_value)

        try:
            result = fifo_capital_gains(transaction_rows, latest_nav_by_scheme)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio.name
        result["schemes"] = scheme_metadata
        result["tax_note"] = (
            result["tax_note"]
            + " Scheme asset-class/category metadata is not yet sufficiently verified for tax classification. "
            + "No equity/debt holding-period threshold, surcharge, cess, exemption, indexation or tax rate is applied."
        )
        return result


@app.get("/v1/portfolios/{portfolio_id}/risk")
def portfolio_historical_risk(
    portfolio_id: int,
    days: int = Query(default=1095, ge=30, le=3650),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Historical NAV-based portfolio risk, scoped to the authenticated owner."""
    require_api_key(x_api_key)
    as_of = datetime.now(timezone.utc).date()
    since = as_of - timedelta(days=days)

    with SessionLocal() as db:
        portfolio = _require_portfolio_owner(db, portfolio_id)
        transactions = db.execute(
            select(PortfolioTransaction)
            .where(
                PortfolioTransaction.portfolio_id == portfolio_id,
                PortfolioTransaction.voided_at.is_(None),
            )
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        positions: dict[int, Decimal] = {}
        for transaction in transactions:
            units = Decimal(transaction.units)
            current_units = positions.get(transaction.scheme_code, Decimal("0"))
            if transaction.transaction_type == "BUY":
                positions[transaction.scheme_code] = current_units + units
            else:
                if units > current_units:
                    raise HTTPException(409, f"Sell transaction exceeds available units for scheme {transaction.scheme_code}")
                positions[transaction.scheme_code] = current_units - units
        positions = {code: units for code, units in positions.items() if units > 0}
        if not positions:
            return {
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio.name,
                "status": "NO_ACTIVE_HOLDINGS",
                "holdings_count": 0,
                "metrics": None,
                "note": "Add active BUY holdings before calculating portfolio risk.",
            }

        weighted_series = []
        holdings = []
        missing_codes = []
        stale_codes = []
        portfolio_value = Decimal("0")
        for code, units in positions.items():
            latest = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code)
                .order_by(desc(NavObservation.nav_date))
                .limit(1)
            ).scalar_one_or_none()
            if latest is None:
                missing_codes.append(code)
                continue
            market_value = units * Decimal(latest.nav_value)
            portfolio_value += market_value
            age_days = (as_of - latest.nav_date).days
            if age_days > MAX_NAV_STALENESS_DAYS:
                stale_codes.append(code)
            history = db.execute(
                select(NavObservation.nav_date, NavObservation.nav_value)
                .where(
                    NavObservation.scheme_code == code,
                    NavObservation.nav_date >= since,
                    NavObservation.nav_date <= latest.nav_date,
                )
                .order_by(NavObservation.nav_date)
            ).all()
            points = [(row.nav_date, float(row.nav_value)) for row in history]
            weighted_series.append((float(market_value), points))
            scheme = db.get(Scheme, code)
            holdings.append({
                "scheme_code": code,
                "scheme_name": scheme.scheme_name if scheme else str(code),
                "units": str(units),
                "market_value": str(market_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "weight_pct": None,
                "nav_date": latest.nav_date.isoformat(),
                "nav_age_days": age_days,
            })

        if missing_codes:
            return {
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio.name,
                "status": "PARTIAL_MISSING_NAV",
                "holdings_count": len(positions),
                "missing_nav_scheme_codes": missing_codes,
                "metrics": None,
                "note": "Portfolio-level risk is withheld when any active holding has no accepted NAV series.",
            }
        for holding in holdings:
            holding["weight_pct"] = (
                float(Decimal(holding["market_value"]) / portfolio_value * 100)
                if portfolio_value > 0 else None
            )
        metrics = portfolio_risk_metrics(weighted_series)
        status = "STALE_NAV" if stale_codes and metrics["status"] == "OK" else metrics["status"]
        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "status": status,
            "lookback_days": days,
            "as_of_date": as_of.isoformat(),
            "portfolio_value": str(portfolio_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "holdings_count": len(positions),
            "holdings": holdings,
            "stale_nav_scheme_codes": stale_codes,
            "maximum_allowed_nav_age_days": MAX_NAV_STALENESS_DAYS,
            "metrics": metrics,
            "note": (
                "Historical NAV-based risk uses current market-value weights held constant over the lookback. "
                "It is a backward-looking estimate, not a forecast. Missing NAV series are never interpolated."
            ),
        }


@app.post("/v1/portfolios/{portfolio_id}/stress")
def portfolio_custom_stress(
    portfolio_id: int,
    payload: PortfolioStressRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Apply an explicit user-defined percentage shock to every active scheme holding."""
    require_api_key(x_api_key)
    with SessionLocal() as db:
        portfolio = _require_portfolio_owner(db, portfolio_id)
        transactions = db.execute(
            select(PortfolioTransaction)
            .where(
                PortfolioTransaction.portfolio_id == portfolio_id,
                PortfolioTransaction.voided_at.is_(None),
            )
            .order_by(PortfolioTransaction.transaction_date, PortfolioTransaction.id)
        ).scalars().all()
        positions: dict[int, Decimal] = {}
        for transaction in transactions:
            units = Decimal(transaction.units)
            current_units = positions.get(transaction.scheme_code, Decimal("0"))
            if transaction.transaction_type == "BUY":
                positions[transaction.scheme_code] = current_units + units
            else:
                if units > current_units:
                    raise HTTPException(409, f"Sell transaction exceeds available units for scheme {transaction.scheme_code}")
                positions[transaction.scheme_code] = current_units - units
        positions = {code: units for code, units in positions.items() if units > 0}
        if not positions:
            raise HTTPException(409, "Portfolio has no active holdings to stress")
        shocks = {item.scheme_code: item.shock_pct for item in payload.shocks}
        if set(shocks) != set(positions):
            raise HTTPException(422, "Provide exactly one explicit shock for every active holding; omitted holdings are not assumed to have zero shock")

        total_value = Decimal("0")
        total_impact = Decimal("0")
        rows = []
        stale_codes = []
        as_of = datetime.now(timezone.utc).date()
        for code, units in positions.items():
            latest = db.execute(
                select(NavObservation)
                .where(NavObservation.scheme_code == code)
                .order_by(desc(NavObservation.nav_date))
                .limit(1)
            ).scalar_one_or_none()
            if latest is None:
                raise HTTPException(409, f"No NAV is available for active holding {code}")
            market_value = units * Decimal(latest.nav_value)
            shock = shocks[code]
            impact = market_value * shock / Decimal("100")
            total_value += market_value
            total_impact += impact
            age_days = (as_of - latest.nav_date).days
            if age_days > MAX_NAV_STALENESS_DAYS:
                stale_codes.append(code)
            scheme = db.get(Scheme, code)
            rows.append({
                "scheme_code": code,
                "scheme_name": scheme.scheme_name if scheme else str(code),
                "market_value": str(market_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "shock_pct": str(shock),
                "estimated_impact": str(impact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "stressed_value": str((market_value + impact).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "nav_date": latest.nav_date.isoformat(),
                "nav_age_days": age_days,
            })
        return {
            "portfolio_id": portfolio_id,
            "portfolio_name": portfolio.name,
            "scenario_name": payload.scenario_name,
            "scenario_type": "USER_DEFINED_SENSITIVITY_NOT_FORECAST",
            "base_portfolio_value": str(total_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "estimated_portfolio_impact": str(total_impact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "stressed_portfolio_value": str((total_value + total_impact).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "stale_nav_scheme_codes": stale_codes,
            "holdings": rows,
            "limitations": [
                "This is a deterministic user-entered sensitivity, not a probability-weighted forecast.",
                "It applies the supplied shock directly to current scheme market values; underlying stock/sector exposures are not inferred.",
                "NAV freshness and source-date limitations remain applicable.",
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
        portfolio = _require_portfolio_owner(db, portfolio_id)
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


# Operator-only historical NAV backfill routes. Execution is locked by default.
from app.nav_history_api import router as nav_history_backfill_router

app.include_router(nav_history_backfill_router)
