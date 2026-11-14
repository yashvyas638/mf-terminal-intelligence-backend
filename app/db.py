from __future__ import annotations

import os
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def database_url() -> str:
    """Return a SQLAlchemy URL compatible with Render/Supabase Postgres URLs."""
    url = os.getenv("DATABASE_URL", "sqlite:///./mf_terminal.db")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_url = database_url()
if os.getenv("ENVIRONMENT", "").lower() == "production" and _url.startswith("sqlite"):
    raise RuntimeError("SQLite is not supported in production; configure a persistent PostgreSQL DATABASE_URL")
_engine_args: dict[str, object] = {"pool_pre_ping": True}
if _url.startswith("sqlite"):
    _engine_args["connect_args"] = {"check_same_thread": False}
engine = create_engine(_url, **_engine_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Scheme(Base):
    __tablename__ = "schemes"
    scheme_code: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_name: Mapped[str] = mapped_column(String(500), nullable=False)
    isin_growth: Mapped[str | None] = mapped_column(String(40))
    isin_dividend_reinvestment: Mapped[str | None] = mapped_column(String(40))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amc: Mapped[str | None] = mapped_column(String(200))
    structure: Mapped[str | None] = mapped_column(String(40))
    category_group: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(160))
    asset_class: Mapped[str | None] = mapped_column(String(40))
    plan_type: Mapped[str | None] = mapped_column(String(20))
    option_type: Mapped[str | None] = mapped_column(String(160))


class IngestionSnapshot(Base):
    __tablename__ = "ingestion_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    records_valid: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_scheme_codes: Mapped[int] = mapped_column(Integer, nullable=False)
    min_nav_date: Mapped[object] = mapped_column(Date, nullable=False)
    max_nav_date: Mapped[object] = mapped_column(Date, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(40), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)


class NavObservation(Base):
    __tablename__ = "nav_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code"), nullable=False)
    nav_date: Mapped[object] = mapped_column(Date, nullable=False)
    nav_value: Mapped[object] = mapped_column(Numeric(20, 8), nullable=False)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("ingestion_snapshots.id"), nullable=False)
    __table_args__ = (
        UniqueConstraint("scheme_code", "nav_date", name="uq_nav_scheme_date"),
        Index("ix_nav_code_date", "scheme_code", "nav_date"),
        CheckConstraint("nav_value > 0", name="ck_nav_observation_value_positive"),
    )


class NavObservationRevision(Base):
    """Append-only provenance for an official NAV correction."""
    __tablename__ = "nav_observation_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code"), nullable=False)
    nav_date: Mapped[object] = mapped_column(Date, nullable=False)
    previous_nav_value: Mapped[object] = mapped_column(Numeric(20, 8), nullable=False)
    replacement_nav_value: Mapped[object] = mapped_column(Numeric(20, 8), nullable=False)
    previous_source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("ingestion_snapshots.id"), nullable=False)
    replacement_source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("ingestion_snapshots.id"), nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_nav_revision_code_date", "scheme_code", "nav_date", "corrected_at"),)


class NavBackfillCheckpoint(Base):
    """Durable state for one bounded AMFI historical NAV request window."""

    __tablename__ = "nav_backfill_checkpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    window_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scheme_type: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[object] = mapped_column(Date, nullable=False)
    end_date: Mapped[object] = mapped_column(Date, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    sampling_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="daily", server_default="daily")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    records_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_class: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("scheme_type IN (1, 2, 3)", name="ck_nav_backfill_scheme_type"),
        CheckConstraint("end_date >= start_date", name="ck_nav_backfill_date_range"),
        CheckConstraint("status IN ('pending', 'running', 'complete', 'failed', 'paused')", name="ck_nav_backfill_status"),
        CheckConstraint("attempts >= 0", name="ck_nav_backfill_attempts_nonnegative"),
        CheckConstraint(
            "records_valid >= 0 AND inserted_rows >= 0 AND updated_rows >= 0 "
            "AND unchanged_rows >= 0 AND duplicate_rows >= 0 AND invalid_rows >= 0",
            name="ck_nav_backfill_counts_nonnegative",
        ),
        CheckConstraint(
            "(status = 'complete' AND completed_at IS NOT NULL) OR "
            "(status <> 'complete' AND completed_at IS NULL)",
            name="ck_nav_backfill_completion_consistent",
        ),
        Index("ix_nav_backfill_status_dates", "status", "start_date", "end_date"),
        Index("ix_nav_backfill_type_dates", "scheme_type", "start_date", "end_date"),
    )

def init_db() -> None:
    Base.metadata.create_all(bind=engine)



class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(8), nullable=False)
    transaction_date: Mapped[object] = mapped_column(Date, nullable=False)
    units: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    nav: Mapped[object] = mapped_column(Numeric(20, 8), nullable=False)
    amount: Mapped[object] = mapped_column(Numeric(20, 2), nullable=False)
    charges: Mapped[object] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        Index("ix_portfolio_txn_portfolio_date", "portfolio_id", "transaction_date"),
        Index("ix_portfolio_txn_scheme", "portfolio_id", "scheme_code"),
        CheckConstraint("transaction_type IN ('BUY', 'SELL')", name="ck_portfolio_txn_type"),
        CheckConstraint("units > 0", name="ck_portfolio_txn_units_positive"),
        CheckConstraint("nav > 0", name="ck_portfolio_txn_nav_positive"),
        CheckConstraint("amount > 0", name="ck_portfolio_txn_amount_positive"),
        CheckConstraint("charges >= 0", name="ck_portfolio_txn_charges_nonnegative"),
    )


class PortfolioTransactionAudit(Base):
    """Append-only record of ledger mutations; never used to calculate holdings."""

    __tablename__ = "portfolio_transaction_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("portfolio_transactions.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (Index("ix_txn_audit_transaction_event", "transaction_id", "event_at"),)

class PortfolioImportBatch(Base):
    """Idempotency ledger for CSV statement imports; stores hashes, never raw statements."""

    __tablename__ = "portfolio_import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    statement_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("portfolio_id", "statement_sha256", name="uq_portfolio_import_hash"),
        Index("ix_portfolio_imported_at", "portfolio_id", "imported_at"),
        CheckConstraint("imported_count > 0", name="ck_portfolio_import_count_positive"),
    )


class PortfolioTransactionIdempotency(Base):
    """Durable idempotency keys for single transaction creation requests."""

    __tablename__ = "portfolio_transaction_idempotency"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("portfolio_transactions.id"), nullable=False, unique=True)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("portfolio_id", "idempotency_key", name="uq_portfolio_transaction_idempotency_key"),
        Index("ix_portfolio_txn_idempotency_created", "portfolio_id", "created_at"),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 128", name="ck_portfolio_txn_idempotency_key_length"),
        CheckConstraint("length(request_sha256) = 64", name="ck_portfolio_txn_idempotency_hash_length"),
    )


class FundWatchlistItem(Base):
    """One authenticated user's saved fund, independent from other users' lists."""

    __tablename__ = "fund_watchlist_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("owner_user_id", "scheme_code", name="uq_fund_watchlist_owner_scheme"),
        Index("ix_fund_watchlist_owner_created", "owner_user_id", "created_at"),
    )


class FundResearchSnapshot(Base):
    """Precomputed, source-derived metrics for global screener ordering."""

    __tablename__ = "fund_research_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code", ondelete="CASCADE"), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    nav_as_of_date: Mapped[object] = mapped_column(Date, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observations: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)
    return_1m: Mapped[float | None] = mapped_column(Float)
    return_3m: Mapped[float | None] = mapped_column(Float)
    return_6m: Mapped[float | None] = mapped_column(Float)
    return_1y: Mapped[float | None] = mapped_column(Float)
    return_3y: Mapped[float | None] = mapped_column(Float)
    return_5y: Mapped[float | None] = mapped_column(Float)
    cagr: Mapped[float | None] = mapped_column(Float)
    volatility: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    sortino_ratio: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    positive_month_rate: Mapped[float | None] = mapped_column(Float)
    rolling_1y_positive_rate: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("scheme_code", "window_days", name="uq_fund_research_scheme_window"),
        CheckConstraint("window_days IN (30, 365, 1095, 1825)", name="ck_fund_research_window_days"),
        CheckConstraint("observations >= 0", name="ck_fund_research_observations_nonnegative"),
        Index("ix_fund_research_window_return_1y", "window_days", "return_1y"),
        Index("ix_fund_research_window_return_3m", "window_days", "return_3m"),
        Index("ix_fund_research_window_return_6m", "window_days", "return_6m"),
        Index("ix_fund_research_window_return_5y", "window_days", "return_5y"),
        Index("ix_fund_research_window_sharpe", "window_days", "sharpe_ratio"),
        Index("ix_fund_research_window_cagr", "window_days", "cagr"),
    )


class BenchmarkIndex(Base):
    """A named benchmark index and its exact return variant."""

    __tablename__ = "benchmark_indices"
    benchmark_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    benchmark_name: Mapped[str] = mapped_column(String(240), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    variant: Mapped[str] = mapped_column(String(8), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("variant IN ('TRI', 'NTR')", name="ck_benchmark_index_total_return_variant"),
        Index("ix_benchmark_provider_name", "provider", "benchmark_name"),
    )


class BenchmarkObservation(Base):
    """A dated official benchmark total-return index observation."""

    __tablename__ = "benchmark_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_code: Mapped[str] = mapped_column(ForeignKey("benchmark_indices.benchmark_code", ondelete="CASCADE"), nullable=False)
    observation_date: Mapped[object] = mapped_column(Date, nullable=False)
    index_value: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("benchmark_code", "observation_date", name="uq_benchmark_observation_date"),
        CheckConstraint("index_value > 0", name="ck_benchmark_index_value_positive"),
        Index("ix_benchmark_observation_code_date", "benchmark_code", "observation_date"),
    )


class BenchmarkObservationRevision(Base):
    """Append-only provenance for a corrected benchmark index value."""

    __tablename__ = "benchmark_observation_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_code: Mapped[str] = mapped_column(String(80), nullable=False)
    observation_date: Mapped[object] = mapped_column(Date, nullable=False)
    previous_value: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    replacement_value: Mapped[object] = mapped_column(Numeric(24, 8), nullable=False)
    previous_source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    replacement_source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("ix_benchmark_revision_code_date", "benchmark_code", "observation_date", "corrected_at"),
    )


class SchemeBenchmarkAssignment(Base):
    """Effective-dated benchmark mapping sourced from a scheme disclosure."""

    __tablename__ = "scheme_benchmark_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code", ondelete="CASCADE"), nullable=False)
    benchmark_code: Mapped[str] = mapped_column(ForeignKey("benchmark_indices.benchmark_code"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[object] = mapped_column(Date, nullable=False)
    valid_to: Mapped[object | None] = mapped_column(Date)
    source_document_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("tier IN (1, 2)", name="ck_scheme_benchmark_tier"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_scheme_benchmark_effective_dates"),
        CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name="ck_scheme_benchmark_verification_status"),
        UniqueConstraint("scheme_code", "tier", "valid_from", name="uq_scheme_benchmark_tier_start"),
        Index("ix_scheme_benchmark_active", "scheme_code", "verification_status", "valid_from", "valid_to"),
    )


class PortfolioGoal(Base):
    """Private goal inputs and user-supplied projection assumptions."""

    __tablename__ = "portfolio_goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    linked_portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount_today: Mapped[object] = mapped_column(Numeric(20, 2), nullable=False)
    target_date: Mapped[object] = mapped_column(Date, nullable=False)
    current_amount: Mapped[object] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    monthly_contribution: Mapped[object] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    inflation_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.06)
    annual_return_low: Mapped[float] = mapped_column(Float, nullable=False)
    annual_return_base: Mapped[float] = mapped_column(Float, nullable=False)
    annual_return_high: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("target_amount_today > 0", name="ck_goal_target_positive"),
        CheckConstraint("current_amount >= 0", name="ck_goal_current_nonnegative"),
        CheckConstraint("monthly_contribution >= 0", name="ck_goal_contribution_nonnegative"),
        CheckConstraint("inflation_rate BETWEEN 0 AND 0.20", name="ck_goal_inflation_bounds"),
        CheckConstraint("annual_return_low BETWEEN -0.20 AND 0.30", name="ck_goal_return_low_bounds"),
        CheckConstraint("annual_return_base BETWEEN -0.20 AND 0.35", name="ck_goal_return_base_bounds"),
        CheckConstraint("annual_return_high BETWEEN -0.20 AND 0.40", name="ck_goal_return_high_bounds"),
        CheckConstraint("annual_return_low <= annual_return_base AND annual_return_base <= annual_return_high", name="ck_goal_return_scenarios_order"),
        Index("ix_portfolio_goal_owner_target_date", "owner_user_id", "target_date"),
    )


class PortfolioReportSnapshot(Base):
    """Immutable, owner-scoped portfolio report payload and reproducibility hash."""

    __tablename__ = "portfolio_report_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_version: Mapped[str] = mapped_column(String(40), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_max_nav_date: Mapped[object | None] = mapped_column(Date)
    __table_args__ = (
        Index("ix_portfolio_report_owner_generated", "owner_user_id", "generated_at"),
        Index("ix_portfolio_report_portfolio_generated", "portfolio_id", "generated_at"),
    )


class FundHoldingDisclosure(Base):
    """Immutable source snapshot for one scheme's dated portfolio disclosure."""

    __tablename__ = "fund_holding_disclosures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_code: Mapped[int] = mapped_column(ForeignKey("schemes.scheme_code", ondelete="CASCADE"), nullable=False)
    as_of_date: Mapped[object] = mapped_column(Date, nullable=False)
    source_document_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_weight_pct: Mapped[object] = mapped_column(Numeric(14, 8), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_disclosure_id: Mapped[int | None] = mapped_column(ForeignKey("fund_holding_disclosures.id"))
    __table_args__ = (
        UniqueConstraint("scheme_code", "as_of_date", "source_sha256", name="uq_holding_disclosure_source"),
        CheckConstraint("row_count > 0", name="ck_holding_disclosure_row_count"),
        Index("ix_holding_disclosure_scheme_date", "scheme_code", "as_of_date", "retrieved_at"),
    )


class FundHolding(Base):
    """Normalized security exposure from one immutable portfolio disclosure."""

    __tablename__ = "fund_holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    disclosure_id: Mapped[int] = mapped_column(ForeignKey("fund_holding_disclosures.id", ondelete="CASCADE"), nullable=False)
    security_id: Mapped[str] = mapped_column(String(80), nullable=False)
    security_name: Mapped[str] = mapped_column(String(240), nullable=False)
    is_isin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    asset_type: Mapped[str | None] = mapped_column(String(80))
    sector: Mapped[str | None] = mapped_column(String(120))
    weight_pct: Mapped[object] = mapped_column(Numeric(14, 8), nullable=False)
    market_value_inr: Mapped[object | None] = mapped_column(Numeric(24, 2))
    __table_args__ = (
        UniqueConstraint("disclosure_id", "security_id", name="uq_holding_disclosure_security"),
        CheckConstraint("weight_pct BETWEEN -1000 AND 1000", name="ck_fund_holding_weight_bounds"),
        Index("ix_fund_holding_disclosure_security", "disclosure_id", "security_id"),
        Index("ix_fund_holding_security", "security_id", "is_isin"),
    )
