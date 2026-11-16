from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg


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
            payload = json.loads(response.read(1_000_001))
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


def main() -> int:
    database_url = require_env("SUPABASE_DB_URL")
    api_url = require_env("MF_TERMINAL_API_URL").rstrip("/")
    api_key = require_env("MF_TERMINAL_API_KEY")
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
                  (SELECT count(DISTINCT owner_user_id) FROM public.portfolios)
                """
            )
            confirmed_users, portfolio_count, portfolio_owners = cur.fetchone()
            report["checks"]["live_tenancy_evidence"] = {
                "confirmed_auth_users": confirmed_users,
                "portfolios": portfolio_count,
                "distinct_portfolio_owners": portfolio_owners,
                "two_account_test_ready": confirmed_users >= 2 and portfolio_owners >= 2,
            }
            if confirmed_users < 2 or portfolio_owners < 2:
                report["warnings"].append(
                    "Live two-account isolation is not evidenced: two confirmed accounts and separately owned portfolios are required."
                )

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
        raise SystemExit(1)
