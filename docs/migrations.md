# Migrations

The live deployment currently uses SQLite.

The application still calls SQLAlchemy `create_all()` for empty databases. For
recent incremental run-metadata columns, startup also applies a small explicit
SQLite compatibility migration.

This is sufficient for the current prototype, but not for the full benchmark
schema roadmap.

Before adding experiments, variants, metric samples, test sites, and richer
result tables, add a proper migration framework such as Alembic.

Migration rules:

- existing runs must remain viewable;
- legacy runs should be marked schema v1 or incomplete, not silently promoted;
- historical antenna and environment snapshots must not change after profile
  edits;
- schema changes should have rollback or backup notes;
- production startup should not rely only on `create_all()`.

Recommended next migration step:

1. Add Alembic configuration.
2. Create a baseline revision for the current schema.
3. Add a revision for current compatibility columns already applied in SQLite.
4. Convert future DB changes into explicit revisions.
