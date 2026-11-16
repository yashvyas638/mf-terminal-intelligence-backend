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
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validated YAML and shell syntax for {len(WORKFLOWS)} operational workflows ({checked} run blocks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
