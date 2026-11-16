import pytest

from app.db import migration_database_url


def test_production_migrations_require_separate_database_credentials(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://runtime:secret@db.example/app")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL must be configured separately"):
        migration_database_url()


def test_migration_database_url_normalizes_postgres_scheme(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgres://migrator:secret@db.example/app")

    assert migration_database_url() == "postgresql+psycopg://migrator:secret@db.example/app"


def test_nonproduction_migrations_can_use_runtime_database_url(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", "postgres://developer:secret@localhost/app")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)

    assert migration_database_url() == "postgresql+psycopg://developer:secret@localhost/app"



def test_production_migrations_reject_shared_runtime_connection(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CI", raising=False)
    shared_url = "postgresql+psycopg://same:secret@db.example/app"
    monkeypatch.setenv("DATABASE_URL", shared_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", shared_url)

    with pytest.raises(RuntimeError, match="must use a separate privileged connection"):
        migration_database_url()
