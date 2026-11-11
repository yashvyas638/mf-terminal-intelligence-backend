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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
