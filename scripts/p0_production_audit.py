from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse



PRIVATE_TABLES = (
    "portfolio_transaction_idempotency",
    "portfolio_goals",
    "portfolio_report_snapshots",
    "fund_watchlist_items",
    "api_rate_limit_buckets",
)
INTERNAL_TABLES = (
    "alembic_version",
    "benchmark_indices",
    "benchmark_observation_revisions",
    "benchmark_observations",
    "fund_holding_disclosures",
    "fund_holdings",
    "fund_research_snapshots",
    "ingestion_snapshots",
    "nav_backfill_checkpoints",
    "nav_observation_revisions",
    "scheme_benchmark_assignments",
)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

CLIENT_READ_ALLOWLIST = {
    "nav_observations": {
        "policy": "nav_observations_authenticated_read",
        "tokens": ("true",),
    },
    "schemes": {
        "policy": "schemes_authenticated_read",
        "tokens": ("true",),
    },
    "portfolios": {
        "policy": "portfolios_owner_read",
        "tokens": ("auth.uid", "owner_user_id"),
    },
    "portfolio_transactions": {
        "policy": "portfolio_transactions_owner_read",
        "tokens": ("auth.uid", "owner_user_id", "portfolio_id"),
    },
    "portfolio_transaction_audit": {
        "policy": "portfolio_transaction_audit_owner_read",
        "tokens": ("auth.uid", "owner_user_id", "transaction_id"),
    },
    "portfolio_import_batches": {
        "policy": "portfolio_import_batches_owner_read",
        "tokens": ("auth.uid", "owner_user_id", "portfolio_id"),
    },
}


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required Actions secret/environment variable is missing: {name}")
    return value


def http_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP check failed for {url}: {response.status}")
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise RuntimeError(f"HTTP check response exceeded the 1 MB safety limit: {urlparse(url).path}")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise RuntimeError(f"Unexpected JSON response from {url}")
            return payload
    except HTTPError as exc:
        raise RuntimeError(f"HTTP check failed for {url}: {exc.code}") from None
    except URLError as exc:
        raise RuntimeError(f"HTTP check could not reach {url}: {type(exc.reason).__name__}") from None


def check_table_privileges(conn, table: str, roles: tuple[str, ...]) -> list[dict]:
    results = []
    with conn.cursor() as cur:
        for role in roles:
            for privilege in PRIVILEGES:
                cur.execute(
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (role, f"public.{table}", privilege),
                )
                granted = bool(cur.fetchone()[0])
                results.append({"role": role, "privilege": privilege, "granted": granted})
    return results


def check_policy(conn, table: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relrowsecurity,
                   p.polname,
                   p.polpermissive,
                   p.polcmd,
                   p.polroles::regrole[]::text,
                   pg_get_expr(p.polqual, p.polrelid),
                   pg_get_expr(p.polwithcheck, p.polrelid)
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_policy p ON p.polrelid = c.oid
             WHERE n.nspname = 'public' AND c.relname = %s
             ORDER BY p.polname
            """,
            (table,),
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"Required production table is missing: public.{table}")
    rls_enabled = bool(rows[0][0])
    policies = [
        {
            "name": row[1],
            "permissive": row[2],
            "command": row[3],
            "roles": row[4] or "",
            "using": row[5],
            "with_check": row[6],
        }
        for row in rows if row[1] is not None
    ]
    deny = next(
        (
            item for item in policies
            if item["name"] == "deny_direct_client_access"
            and item["permissive"] is False
            and item["command"] == "*"
            and "anon" in item["roles"]
            and "authenticated" in item["roles"]
            and item["using"] == "false"
            and item["with_check"] == "false"
        ),
        None,
    )
    return {"rls_enabled": rls_enabled, "policies": policies, "restrictive_deny_verified": bool(deny)}



def check_public_table_surface(conn) -> tuple[dict[str, dict], list[str]]:
    """Fail closed on any new or widened direct Supabase client table grant."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind IN ('r', 'p')
             ORDER BY c.relname
            """
        )
        table_names = [row[0] for row in cur.fetchall()]

    if not table_names:
        raise RuntimeError("No public application tables were found during the client-surface audit.")

    report: dict[str, dict] = {}
    failures: list[str] = []
    for table in table_names:
        posture = check_policy(conn, table)
        privileges = check_table_privileges(conn, table, ("anon", "authenticated"))
        granted = {
            role: {item["privilege"] for item in privileges if item["role"] == role and item["granted"]}
            for role in ("anon", "authenticated")
        }
        expected_auth = {"SELECT"} if table in CLIENT_READ_ALLOWLIST else set()
        expected = {"anon": set(), "authenticated": expected_auth}
        grants_match = granted == expected
        table_result = {
            "rls_enabled": posture["rls_enabled"],
            "anon_privileges": sorted(granted["anon"]),
            "authenticated_privileges": sorted(granted["authenticated"]),
            "expected_authenticated_privileges": sorted(expected_auth),
            "client_grants_match_allowlist": grants_match,
        }

        if not posture["rls_enabled"]:
            failures.append(f"RLS is not enabled on public.{table}")
        if not grants_match:
            failures.append(f"Unexpected anon/authenticated table grants on public.{table}")

        if table in CLIENT_READ_ALLOWLIST:
            expected_policy = CLIENT_READ_ALLOWLIST[table]
            matching = [
                policy for policy in posture["policies"]
                if policy["command"] in ("r", "*") and policy["permissive"] is True
            ]
            selected = next(
                (policy for policy in matching if policy["name"] == expected_policy["policy"]),
                None,
            )
            policy_ok = (
                len(matching) == 1
                and selected is not None
                and "authenticated" in selected["roles"]
                and all(token in (selected["using"] or "").lower() for token in expected_policy["tokens"])
            )
            table_result["expected_select_policy"] = expected_policy["policy"]
            table_result["select_policy_verified"] = policy_ok
            if not policy_ok:
                failures.append(f"Authenticated SELECT policy is missing, widened or ambiguous on public.{table}")
        report[table] = table_result

    unexpected_allowlist = sorted(set(CLIENT_READ_ALLOWLIST) - set(table_names))
    if unexpected_allowlist:
        failures.append(f"Expected client-readable tables are missing: {unexpected_allowlist}")
    return report, failures



def evaluate_tenancy_integrity(
    *,
    confirmed_users: int,
    portfolio_count: int,
    portfolio_owners: int,
    portfolios_without_confirmed_owner: int,
    portfolio_goals: int,
    goals_with_confirmed_owner: int,
    goals_without_confirmed_owner: int,
    goals_with_cross_owner_portfolio_link: int,
) -> tuple[dict, list[str]]:
    """Evaluate ownership invariants independently of the live database connection."""
    evidence = {
        "confirmed_auth_users": confirmed_users,
        "portfolios": portfolio_count,
        "distinct_portfolio_owners": portfolio_owners,
        "portfolios_without_confirmed_auth_owner": portfolios_without_confirmed_owner,
        "portfolio_goals": portfolio_goals,
        "goals_with_confirmed_auth_owner": goals_with_confirmed_owner,
        "goals_without_confirmed_auth_owner": goals_without_confirmed_owner,
        "goals_with_cross_owner_portfolio_link": goals_with_cross_owner_portfolio_link,
        "two_account_test_ready": confirmed_users >= 2 and portfolio_owners >= 2,
    }
    failures: list[str] = []
    if portfolios_without_confirmed_owner:
        failures.append(
            "Portfolio ownership integrity failed: one or more portfolios do not belong to a confirmed Auth account."
        )
    if goals_without_confirmed_owner:
        failures.append(
            "Portfolio-goal ownership integrity failed: one or more goal records do not belong to a confirmed Auth account."
        )
    if goals_with_cross_owner_portfolio_link:
        failures.append(
            "Portfolio-goal linkage integrity failed: one or more goals are linked to a portfolio owned by a different account."
        )
    if confirmed_users < 2 or portfolio_owners < 2:
        failures.append(
            "P0 tenancy gate failed: two real confirmed accounts and at least two separately owned portfolios are required before operational readiness can pass."
        )
    return evidence, failures


def main() -> int:
    database_url = require_env("SUPABASE_DB_URL")
    api_url = require_env("MF_TERMINAL_API_URL").rstrip("/")
    parsed_api_url = urlparse(api_url)
    if parsed_api_url.scheme != "https" or not parsed_api_url.hostname or parsed_api_url.username or parsed_api_url.password:
        raise RuntimeError("MF_TERMINAL_API_URL must be a credential-free HTTPS origin.")
    api_key = require_env("MF_TERMINAL_API_KEY")
    import psycopg

    report: dict = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_ref": "zgfdvhzhvccsfmpoaqah",
        "checks": {},
        "warnings": [],
        "failures": [],
    }

    health = http_json(f"{api_url}/health")
    report["checks"]["render_health"] = health
    if health.get("status") != "ok" or health.get("database") != "reachable":
        report["failures"].append("Render health/database check did not report ready")

    nav = http_json(f"{api_url}/v1/nav/status", {"X-API-Key": api_key})
    snapshot = nav.get("latest_snapshot")
    report["checks"]["nav_status"] = {
        "status": nav.get("status"),
        "scheme_master_count": nav.get("scheme_master_count"),
        "freshness_status": nav.get("freshness_status"),
        "effective_nav_status": nav.get("effective_nav_status"),
        "retrieval_age_hours": nav.get("retrieval_age_hours"),
        "effective_nav_age_days": nav.get("effective_nav_age_days"),
        "latest_snapshot_id": snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None,
        "quality_status": snapshot.get("quality_status") if isinstance(snapshot, dict) else None,
        "max_nav_date": snapshot.get("max_nav_date") if isinstance(snapshot, dict) else None,
    }
    if nav.get("status") != "ok" or not snapshot:
        report["failures"].append("No committed production NAV snapshot is available")
    if nav.get("freshness_status") != "FRESH_RETRIEVAL":
        report["failures"].append("Production NAV retrieval is stale")
    if nav.get("effective_nav_status") != "FRESH_EFFECTIVE_DATE":
        report["failures"].append("Production NAV effective date is stale")

    with psycopg.connect(database_url, connect_timeout=15, sslmode="require") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM public.alembic_version LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Alembic migration head is missing")
            report["checks"]["alembic_revision"] = row[0]

            cur.execute(
                """
                SELECT
                  (SELECT count(*) FROM auth.users WHERE email_confirmed_at IS NOT NULL),
                  (SELECT count(*) FROM public.portfolios),
                  (SELECT count(DISTINCT owner_user_id) FROM public.portfolios),
                  (SELECT count(*) FROM public.portfolios p
                    LEFT JOIN auth.users u ON u.id::text = p.owner_user_id
                    WHERE u.id IS NULL OR u.email_confirmed_at IS NULL),
                  (SELECT count(*) FROM public.portfolio_goals),
                  (SELECT count(*) FROM public.portfolio_goals g
                    JOIN auth.users u ON u.id::text = g.owner_user_id
                    WHERE u.email_confirmed_at IS NOT NULL),
                  (SELECT count(*) FROM public.portfolio_goals g
                    LEFT JOIN auth.users u ON u.id::text = g.owner_user_id
                    WHERE u.id IS NULL OR u.email_confirmed_at IS NULL),
                  (SELECT count(*) FROM public.portfolio_goals g
                    LEFT JOIN public.portfolios p ON p.id = g.linked_portfolio_id
                    WHERE g.linked_portfolio_id IS NOT NULL
                      AND (p.id IS NULL OR p.owner_user_id IS DISTINCT FROM g.owner_user_id))
                """
            )
            (
                confirmed_users, portfolio_count, portfolio_owners,
                portfolios_without_confirmed_owner,
                portfolio_goals, goals_with_confirmed_owner, goals_without_confirmed_owner,
                goals_with_cross_owner_portfolio_link,
            ) = cur.fetchone()
            tenancy_evidence, tenancy_failures = evaluate_tenancy_integrity(
                confirmed_users=confirmed_users,
                portfolio_count=portfolio_count,
                portfolio_owners=portfolio_owners,
                portfolios_without_confirmed_owner=portfolios_without_confirmed_owner,
                portfolio_goals=portfolio_goals,
                goals_with_confirmed_owner=goals_with_confirmed_owner,
                goals_without_confirmed_owner=goals_without_confirmed_owner,
                goals_with_cross_owner_portfolio_link=goals_with_cross_owner_portfolio_link,
            )
            report["checks"]["live_tenancy_evidence"] = tenancy_evidence
            report["failures"].extend(tenancy_failures)

        private_results = {}
        for table in PRIVATE_TABLES:
            posture = check_policy(conn, table)
            privileges = check_table_privileges(conn, table, ("anon", "authenticated"))
            service_role = check_table_privileges(conn, table, ("service_role",))
            service_select = next(item["granted"] for item in service_role if item["privilege"] == "SELECT")
            client_denied = not any(item["granted"] for item in privileges)
            private_results[table] = {
                **posture,
                "client_privileges_all_denied": client_denied,
                "service_role_select": service_select,
            }
            if not posture["rls_enabled"] or not posture["restrictive_deny_verified"] or not client_denied or not service_select:
                report["failures"].append(f"Private-table security posture failed for public.{table}")
        report["checks"]["private_tables"] = private_results

        internal_results = {}
        for table in INTERNAL_TABLES:
            posture = check_policy(conn, table)
            privileges = check_table_privileges(conn, table, ("anon", "authenticated"))
            client_denied = not any(item["granted"] for item in privileges)
            internal_results[table] = {
                "rls_enabled": posture["rls_enabled"],
                "policy_count": len(posture["policies"]),
                "client_privileges_all_denied": client_denied,
            }
            if not posture["rls_enabled"] or not client_denied:
                report["failures"].append(f"Internal-table client access check failed for public.{table}")
        report["checks"]["internal_tables"] = internal_results

        public_surface, surface_failures = check_public_table_surface(conn)
        report["checks"]["public_table_surface"] = {
            "table_count": len(public_surface),
            "approved_authenticated_read_tables": sorted(CLIENT_READ_ALLOWLIST),
            "tables": public_surface,
        }
        report["failures"].extend(surface_failures)

    report["result"] = "FAIL" if report["failures"] else ("PASS_WITH_WARNINGS" if report["warnings"] else "PASS")
    print(json.dumps(report, indent=2, default=str), flush=True)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "result": "FAIL",
            "error": type(exc).__name__,
            "message": str(exc),
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        }, indent=2), flush=True)
        raise SystemExit(1) from None
