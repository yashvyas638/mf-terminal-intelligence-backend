# Start here — MF Terminal Intelligence

This repository is the active backend for MF Terminal Intelligence. Development is happening on the protected working branch:

`audit/production-foundation`

Do not create a second repository, upload a ZIP over the existing project, or deploy intermediate commits.

## Current delivery rule

Build and verify the product in sequence through the roadmap (P0 → P6). Final production integration is a separate release gate and happens only after the full implementation and review are complete.

Until then:
- Keep all work on `audit/production-foundation`.
- Keep `main` unchanged; do not merge without explicit approval.
- Do not run production Supabase migrations or change production grants.
- Do not deploy a candidate commit to Render.
- Never paste database URLs, passwords, API keys or tokens into chat, source files, issues or logs.
- Keep production financial and NAV data intact; no reset, truncate or destructive migration.

## How to follow progress

1. Read [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) for phase status and acceptance evidence.
2. Read [Product Blueprint](docs/PRODUCT_BLUEPRINT.md) for product scope.
3. Read [Engineering Playbook](docs/ENGINEERING_PLAYBOOK.md) for delivery and quality gates.
4. Read [Architecture and Data Model](docs/ARCHITECTURE_AND_DATA_MODEL.md) for system design.
5. Read [UX and Design System](docs/UX_AND_DESIGN_SYSTEM.md) for interface requirements.
6. Read [P0 Security Remediation](docs/P0_SECURITY_REMEDIATION.md) before any production database permission work.

## Final release sequence

The final release is not complete until the approved GitHub SHA is verified, full CI passes, migrations are rehearsed and reviewed, Supabase connection role and grants are confirmed, Render environment and deployed SHA are verified, production smoke tests pass, backups/rollback are documented, and the user explicitly signs off.

The API health endpoint alone is not proof that NAV ingestion, portfolio workflows, permissions, or the dashboard are production-ready.
