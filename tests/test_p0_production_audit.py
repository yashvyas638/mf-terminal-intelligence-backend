from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

audit_path = Path(__file__).resolve().parents[1] / "scripts" / "p0_production_audit.py"
audit_spec = spec_from_file_location("p0_production_audit", audit_path)
assert audit_spec is not None and audit_spec.loader is not None
audit = module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)


class FakeCursor:
    def __init__(self, table_names: list[str]) -> None:
        self.table_names = table_names

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def fetchall(self) -> list[tuple[str]]:
        return [(name,) for name in self.table_names]


class FakeConnection:
    def __init__(self, table_names: list[str]) -> None:
        self.table_names = table_names

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.table_names)


def policy_for(table: str) -> dict[str, Any]:
    config = audit.CLIENT_READ_ALLOWLIST.get(table)
    if not config:
        return {"rls_enabled": True, "policies": [], "restrictive_deny_verified": False}
    tokens = config["tokens"]
    expression = " ".join(tokens)
    return {
        "rls_enabled": True,
        "policies": [{
            "name": config["policy"],
            "permissive": True,
            "command": "r",
            "roles": "{authenticated}",
            "using": expression,
            "with_check": None,
        }],
        "restrictive_deny_verified": False,
    }


def privileges_for(table: str, *, unexpected: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for role in ("anon", "authenticated"):
        for privilege in audit.PRIVILEGES:
            granted = table in audit.CLIENT_READ_ALLOWLIST and role == "authenticated" and privilege == "SELECT"
            if unexpected == (role, privilege):
                granted = True
            rows.append({"role": role, "privilege": privilege, "granted": granted})
    return rows


def install_mocks(monkeypatch, table_names: list[str], *, unexpected=None, missing_rls=None, extra_policy=None) -> None:
    def fake_policy(_conn, table: str) -> dict[str, Any]:
        result = policy_for(table)
        if table == missing_rls:
            result["rls_enabled"] = False
        if table == extra_policy:
            result["policies"].append({
                "name": "unexpected_public_read",
                "permissive": True,
                "command": "r",
                "roles": "{authenticated}",
                "using": "true",
                "with_check": None,
            })
        return result

    monkeypatch.setattr(audit, "check_policy", fake_policy)
    monkeypatch.setattr(
        audit,
        "check_table_privileges",
        lambda _conn, table, _roles: privileges_for(table, unexpected=unexpected),
    )


def test_public_table_surface_accepts_only_approved_authenticated_select(monkeypatch) -> None:
    names = sorted([*audit.CLIENT_READ_ALLOWLIST, "internal_private_table"])
    install_mocks(monkeypatch, names)
    report, failures = audit.check_public_table_surface(FakeConnection(names))
    assert failures == []
    assert report["schemes"]["authenticated_privileges"] == ["SELECT"]
    assert report["internal_private_table"]["authenticated_privileges"] == []


def test_public_table_surface_rejects_unexpected_anon_grant(monkeypatch) -> None:
    names = sorted([*audit.CLIENT_READ_ALLOWLIST, "internal_private_table"])
    install_mocks(monkeypatch, names, unexpected=("anon", "SELECT"))
    _report, failures = audit.check_public_table_surface(FakeConnection(names))
    assert any("Unexpected anon/authenticated table grants" in item for item in failures)


def test_public_table_surface_rejects_missing_rls(monkeypatch) -> None:
    names = sorted([*audit.CLIENT_READ_ALLOWLIST, "internal_private_table"])
    install_mocks(monkeypatch, names, missing_rls="internal_private_table")
    _report, failures = audit.check_public_table_surface(FakeConnection(names))
    assert "RLS is not enabled on public.internal_private_table" in failures


def test_public_table_surface_rejects_additional_permissive_select_policy(monkeypatch) -> None:
    names = sorted([*audit.CLIENT_READ_ALLOWLIST, "internal_private_table"])
    install_mocks(monkeypatch, names, extra_policy="schemes")
    _report, failures = audit.check_public_table_surface(FakeConnection(names))
    assert "Authenticated SELECT policy is missing, widened or ambiguous on public.schemes" in failures


def test_public_table_surface_rejects_missing_allowlisted_relation(monkeypatch) -> None:
    names = ["schemes"]
    install_mocks(monkeypatch, names)
    _report, failures = audit.check_public_table_surface(FakeConnection(names))
    assert any("Expected client-readable tables are missing" in item for item in failures)



def test_tenancy_integrity_passes_only_with_two_confirmed_owners() -> None:
    evidence, failures = audit.evaluate_tenancy_integrity(
        confirmed_users=2,
        portfolio_count=2,
        portfolio_owners=2,
        portfolios_without_confirmed_owner=0,
        portfolio_goals=2,
        goals_with_confirmed_owner=2,
        goals_without_confirmed_owner=0,
        goals_with_cross_owner_portfolio_link=0,
    )
    assert evidence["two_account_test_ready"] is True
    assert evidence["goals_with_confirmed_auth_owner"] == 2
    assert failures == []


def test_tenancy_integrity_rejects_cross_owner_goal_link() -> None:
    _evidence, failures = audit.evaluate_tenancy_integrity(
        confirmed_users=2,
        portfolio_count=2,
        portfolio_owners=2,
        portfolios_without_confirmed_owner=0,
        portfolio_goals=1,
        goals_with_confirmed_owner=1,
        goals_without_confirmed_owner=0,
        goals_with_cross_owner_portfolio_link=1,
    )
    assert any("linked to a portfolio owned by a different account" in item for item in failures)


def test_tenancy_integrity_rejects_unconfirmed_owners_and_goals() -> None:
    _evidence, failures = audit.evaluate_tenancy_integrity(
        confirmed_users=2,
        portfolio_count=2,
        portfolio_owners=2,
        portfolios_without_confirmed_owner=1,
        portfolio_goals=1,
        goals_with_confirmed_owner=0,
        goals_without_confirmed_owner=1,
        goals_with_cross_owner_portfolio_link=0,
    )
    assert any("Portfolio ownership integrity failed" in item for item in failures)
    assert any("Portfolio-goal ownership integrity failed" in item for item in failures)


def test_tenancy_integrity_blocks_single_account_readiness() -> None:
    evidence, failures = audit.evaluate_tenancy_integrity(
        confirmed_users=1,
        portfolio_count=1,
        portfolio_owners=1,
        portfolios_without_confirmed_owner=0,
        portfolio_goals=0,
        goals_with_confirmed_owner=0,
        goals_without_confirmed_owner=0,
        goals_with_cross_owner_portfolio_link=0,
    )
    assert evidence["two_account_test_ready"] is False
    assert any("two real confirmed accounts" in item for item in failures)
