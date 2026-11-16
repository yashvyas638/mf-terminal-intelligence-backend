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
        if "head-object" not in remote_script or "sha256sum \"$REMOTE_COPY\"" not in remote_script:
            errors.append("backup workflow: R2 copy must be downloaded and verified by size and SHA-256")
        if cleanup_step.get("if") != "always()" or "mf-terminal-intelligence-*.tar.gz.age" not in cleanup_script:
            errors.append("backup workflow: encrypted runner copy must be cleaned in an always() step")

    migration_env = Path("migrations/env.py").read_text(encoding="utf-8")
    db_config = Path("app/db.py").read_text(encoding="utf-8")
    if "migration_database_url()" not in migration_env:
        errors.append("migrations/env.py: Alembic must use the dedicated migration URL")
    if "MIGRATION_DATABASE_URL must be configured separately" not in db_config:
        errors.append("app/db.py: production migrations must fail closed without a dedicated URL")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validated YAML and shell syntax for {len(WORKFLOWS)} operational workflows ({checked} run blocks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
