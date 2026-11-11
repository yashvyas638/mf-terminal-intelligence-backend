from __future__ import annotations

import os
from datetime import datetime
from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, create_engine
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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)



class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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