"""Operator-only API for planning and executing AMFI history backfills.

No route can run a historical fetch until both deployment flags are explicitly
enabled after live verification of AMFI's official History form contract.
"""
from __future__ import annotations

import hmac
import os
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, StrictInt, model_validator

from app.nav_history_backfill import (
    create_history_backfill_plan,
    history_backfill_status,
    run_history_backfill_batch,
)

router = APIRouter(tags=["NAV historical backfill"])


def _require_operator_key(value: str | None) -> None:
    expected = os.getenv("API_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Operator authentication is not configured")
    if not value or not hmac.compare_digest(value, expected):
        raise HTTPException(401, "A valid server operator key is required")


def _execution_gates() -> dict[str, bool]:
    return {
        "source_contract_verified": os.getenv("AMFI_HISTORY_CONTRACT_VERIFIED", "").lower() == "true",
        "backfill_enabled": os.getenv("AMFI_HISTORY_BACKFILL_ENABLED", "").lower() == "true",
    }


class HistoryBackfillPlanRequest(BaseModel):
    start_date: date
    end_date: date
    scheme_types: list[StrictInt] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=3)
    max_window_days: int = Field(default=7, ge=1, le=90)

    @model_validator(mode="after")
    def validate_plan(self) -> "HistoryBackfillPlanRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if len(set(self.scheme_types)) != len(self.scheme_types):
            raise ValueError("scheme_types must not contain duplicates")
        if any(isinstance(value, bool) or value not in {1, 2, 3} for value in self.scheme_types):
            raise ValueError("scheme_types must contain only 1, 2, or 3")
        return self


class HistoryBackfillRunRequest(BaseModel):
    limit: int = Field(default=1, ge=1, le=20)
    max_attempts: int = Field(default=3, ge=1, le=5)


@router.post("/v1/nav/backfill/plan")
def plan_nav_history_backfill(
    payload: HistoryBackfillPlanRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Create idempotent checkpoints only; this endpoint never calls AMFI."""
    _require_operator_key(x_api_key)
    try:
        return create_history_backfill_plan(
            payload.start_date,
            payload.end_date,
            tuple(payload.scheme_types),
            max_window_days=payload.max_window_days,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/v1/nav/backfill/status")
def get_nav_history_backfill_status(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Return aggregate checkpoint and reconciliation counts for operators."""
    _require_operator_key(x_api_key)
    return {**history_backfill_status(), "execution_gates": _execution_gates()}


@router.post("/v1/nav/backfill/run")
def run_nav_history_backfill(
    payload: HistoryBackfillRunRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Run a bounded batch only after both explicit source/release gates are true."""
    _require_operator_key(x_api_key)
    gates = _execution_gates()
    if not all(gates.values()):
        raise HTTPException(
            409,
            {
                "detail": "Historical NAV ingestion is locked until the official AMFI history contract is verified and the operator enables backfill.",
                "execution_gates": gates,
            },
        )
    try:
        return run_history_backfill_batch(
            limit=payload.limit,
            max_attempts=payload.max_attempts,
            enabled=True,
            source_contract_verified=True,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None
