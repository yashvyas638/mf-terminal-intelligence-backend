from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


WORKFLOWS = (
    Path(".github/workflows/supabase-free-tier-backup.yml"),
    Path(".github/workflows/p0-production-readiness.yml"),
)
GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def main() -> int:
    errors: list[str] = []
    checked = 0
    for workflow_path in WORKFLOWS:
        document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            errors.append(f"{workflow_path}: missing jobs mapping")
            continue
        for job_name, job in jobs.items():
            steps = job.get("steps", []) if isinstance(job, dict) else []
            for index, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    errors.append(f"{workflow_path}:{job_name}: step {index} is not a mapping")
                    continue
                run_script = step.get("run")
                if not isinstance(run_script, str):
                    continue
                checked += 1
                shell_script = GITHUB_EXPRESSION.sub("github_expression_value", run_script)
                result = subprocess.run(
                    ["bash", "-n"],
                    input=shell_script,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode:
                    errors.append(
                        f"{workflow_path}:{job_name}: step {step.get('name', index)!r} "
                        f"has invalid shell syntax: {result.stderr.strip()}"
                    )
    render_path = Path("render.yaml")
    if not render_path.is_file():
        errors.append("render.yaml: missing deployment blueprint")
    else:
        render_document = yaml.safe_load(render_path.read_text(encoding="utf-8"))
        services = render_document.get("services", []) if isinstance(render_document, dict) else []
        web_services = [item for item in services if isinstance(item, dict) and item.get("type") == "web"]
        if len(web_services) != 1:
            errors.append("render.yaml: expected exactly one web service in the candidate blueprint")
        for service in web_services:
            env_vars = {
                item.get("key"): item
                for item in service.get("envVars", [])
                if isinstance(item, dict) and item.get("key")
            }
            for required in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
                if required not in env_vars or env_vars[required].get("sync") is not False:
                    errors.append(
                        f"render.yaml: {required} must be declared as a non-synchronised secret"
                    )
            command = str(service.get("startCommand", ""))
            migration = command.find("alembic upgrade head")
            unset = command.find("unset MIGRATION_DATABASE_URL")
            server = command.find("uvicorn app.main:app")
            if not (0 <= migration < unset < server):
                errors.append(
                    "render.yaml: run Alembic with the migration-only URL, unset it, then start Uvicorn"
                )
            procfile_path = Path("Procfile")
            if procfile_path.is_file():
                procfile_command = procfile_path.read_text(encoding="utf-8").strip()
                expected_command = f"web: {command}"
                if procfile_command != expected_command:
                    errors.append("Procfile and render.yaml must use the same migration-safe startup command")

    backup_path = Path(".github/workflows/supabase-free-tier-backup.yml")
    if not backup_path.is_file():
        errors.append("backup workflow: missing encrypted backup workflow")
    else:
        backup_document = yaml.safe_load(backup_path.read_text(encoding="utf-8"))
        jobs = backup_document.get("jobs", {}) if isinstance(backup_document, dict) else {}
        backup_job = jobs.get("backup", {}) if isinstance(jobs, dict) else {}
        steps = backup_job.get("steps", []) if isinstance(backup_job, dict) else []
        step_by_name = {
            str(step.get("name", "")): step
            for step in steps
            if isinstance(step, dict)
        }
        export_step = step_by_name.get("Export, checksum and encrypt database", {})
        upload_step = step_by_name.get("Upload encrypted GitHub recovery copy", {})
        remote_step = step_by_name.get("Copy encrypted backup to mandatory off-site storage", {})
        cleanup_step = step_by_name.get("Remove encrypted runner copy", {})
        export_script = str(export_step.get("run", ""))
        dump_commands = re.findall(r"(?m)^\\s*supabase db dump[^\\n]*", export_script)
        if len(dump_commands) != 3 or any("--db-url" not in command or "--remote" in command for command in dump_commands):
            errors.append("backup workflow: every Supabase dump must use the supported --db-url connection-string flag")
        upload_path = str(upload_step.get("with", {}).get("path", ""))
        remote_script = str(remote_step.get("run", ""))
        cleanup_script = str(cleanup_step.get("run", ""))
        names = list(step_by_name)
        required_order = [
            "Export, checksum and encrypt database",
            "Upload encrypted GitHub recovery copy",
            "Copy encrypted backup to mandatory off-site storage",
            "Remove encrypted runner copy",
        ]
        positions = [names.index(name) for name in required_order if name in names]
        if len(positions) != len(required_order) or positions != sorted(positions):
            errors.append("backup workflow: encrypted archive export/upload/R2 verification/cleanup order is invalid")
        if "rm -f \"$ARCHIVE.age\"" in export_script:
            errors.append("backup workflow: export step deletes the encrypted archive before later upload steps")
        if "steps.backup.outputs.archive" not in upload_path:
            errors.append("backup workflow: GitHub recovery artifact must use the encrypted archive output")
        if "steps.backup.outputs.stamp" not in remote_script:
            errors.append("backup workflow: R2 object key and verification path must use the step output stamp")
        # Step-local shell variables do not survive between GitHub Actions run steps.
        # If the R2 step uses $STAMP, it must import the prior step output explicitly.
        if re.search(r"(?<![\w])\$STAMP\b", remote_script) and ('STAMP="' + "$" + "{{ steps.backup.outputs.stamp }}" + '"') not in remote_script:
            errors.append("backup workflow: R2 step references $STAMP without importing steps.backup.outputs.stamp")
        if "head-object" not in remote_script or "sha256sum \"$REMOTE_COPY\"" not in remote_script:
            errors.append("backup workflow: R2 copy must be downloaded and verified by size and SHA-256")
        if "MONTHLY_REMOTE_SIZE" not in remote_script or "sha256sum \"$REMOTE_COPY_MONTHLY\"" not in remote_script:
            errors.append("backup workflow: monthly R2 copy must also be verified by size and SHA-256")
        if cleanup_step.get("if") != "always()" or "mf-terminal-intelligence-*.tar.gz.age" not in cleanup_script:
            errors.append("backup workflow: encrypted runner copy must be cleaned in an always() step")

    p0_path = Path(".github/workflows/p0-production-readiness.yml")
    if not p0_path.is_file():
        errors.append("P0 audit workflow: missing production readiness workflow")
    else:
        p0_document = yaml.safe_load(p0_path.read_text(encoding="utf-8"))
        p0_jobs = p0_document.get("jobs", {}) if isinstance(p0_document, dict) else {}
        p0_job = p0_jobs.get("audit", {}) if isinstance(p0_jobs, dict) else {}
        p0_steps = p0_job.get("steps", []) if isinstance(p0_job, dict) else []
        p0_by_name = {
            str(step.get("name", "")): step
            for step in p0_steps
            if isinstance(step, dict)
        }
        p0_names = list(p0_by_name)
        syntax_name = "Validate audit script syntax"
        config_name = "Validate audit configuration"
        evidence_name = "Retain audit evidence"
        if syntax_name not in p0_names or config_name not in p0_names or p0_names.index(syntax_name) > p0_names.index(config_name):
            errors.append("P0 audit workflow: validate Python syntax before checking secrets")
        config_script = str(p0_by_name.get(config_name, {}).get("run", ""))
        evidence_step = p0_by_name.get(evidence_name, {})
        evidence_path = str(evidence_step.get("with", {}).get("path", ""))
        if "BLOCKED_CONFIGURATION" not in config_script or "p0-audit-report.json" not in config_script:
            errors.append("P0 audit workflow: write a redacted BLOCKED_CONFIGURATION report before exiting on missing secrets")
        if evidence_step.get("if") != "always()" or evidence_path != "p0-audit-report.json":
            errors.append("P0 audit workflow: retain the diagnostic report with an always() artifact step")

    migration_env = Path("migrations/env.py").read_text(encoding="utf-8")
    db_config = Path("app/db.py").read_text(encoding="utf-8")
    if "migration_database_url()" not in migration_env:
        errors.append("migrations/env.py: Alembic must use the dedicated migration URL")
    if "MIGRATION_DATABASE_URL must be configured separately" not in db_config:
        errors.append("app/db.py: production migrations must fail closed without a dedicated URL")
    app_main = Path("app/main.py").read_text(encoding="utf-8")
    if "r.rolsuper" not in app_main or "must not use a PostgreSQL superuser" not in app_main:
        errors.append("app/main.py: API runtime must reject PostgreSQL superuser credentials")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validated YAML and shell syntax for {len(WORKFLOWS)} operational workflows ({checked} run blocks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
