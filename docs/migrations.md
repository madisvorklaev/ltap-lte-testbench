# Migrations

The live deployment currently uses SQLite.

Production startup now uses Alembic. The baseline revision is:

```text
20260722_0001_initial_schema
```

Development tests may still use SQLAlchemy `create_all()` for empty in-memory
SQLite databases. File-backed databases should go through Alembic.

Migration rules:

- existing runs must remain viewable;
- legacy runs should be marked schema v1 or incomplete, not silently promoted;
- historical antenna and environment snapshots must not change after profile
  edits;
- schema changes should have rollback or backup notes;
- production startup should not rely only on `create_all()`.

Startup behavior:

1. Empty file-backed databases run `alembic upgrade head`.
2. Pre-Alembic SQLite databases are detected by existing tables without an
   `alembic_version` table.
3. Legacy SQLite databases get compatibility columns for benchmark metadata,
   batch worker fields, antenna unknown-gain reason, and attempt environment
   snapshots.
4. After compatibility backfill, legacy databases are stamped at the current
   head revision.
5. In-memory SQLite tests still use direct metadata creation.

Operational notes:

- Back up `var/ltap-testbench.sqlite3` before deploying a new migration.
- Do not edit an existing revision after it has been used on a live database.
- Add a new Alembic revision for every schema change.
- Keep legacy result rows visible and comparison-ineligible unless their stored
  protocol and integrity metadata proves otherwise.
