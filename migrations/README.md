# Database migrations

The initial baseline adopts existing databases that were initialized with SQLAlchemy
`create_all`; it creates missing tables without dropping existing data.

For a new or existing database:

```bash
alembic upgrade head
```

Before deploying schema changes, back up the database and review the generated migration.
Create new revisions with:

```bash
alembic revision --autogenerate -m "describe schema change"
```

Inspect generated operations manually. Never assume autogenerate correctly handles data
migrations, renames, constraints, or large-table operations. Do not run downgrade against
production without a tested backup and an explicit recovery plan.
