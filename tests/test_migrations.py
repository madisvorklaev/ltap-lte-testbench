from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, text

from ltap_testbench.db.base import run_migrations


def _sqlite_engine(path: Path):
    return create_engine(f"sqlite:///{path}", future=True)


def test_alembic_initializes_empty_sqlite_database() -> None:
    with TemporaryDirectory() as tmp:
        engine = _sqlite_engine(Path(tmp) / "empty.sqlite3")

        run_migrations(engine)

        with engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text("select name from sqlite_master where type = 'table'")
                )
            }
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()

        assert "benchmark_protocols" in tables
        assert "test_batches" in tables
        assert "metric_samples" in tables
        assert revision == "20260722_0001"


def test_legacy_sqlite_database_is_stamped_and_backfilled() -> None:
    with TemporaryDirectory() as tmp:
        engine = _sqlite_engine(Path(tmp) / "legacy.sqlite3")
        with engine.begin() as connection:
            connection.execute(text("create table router_profiles (id integer primary key)"))
            connection.execute(text("create table test_runs (id integer primary key)"))
            connection.execute(text("create table test_batches (id integer primary key)"))
            connection.execute(text("create table antenna_profiles (id integer primary key)"))
            connection.execute(text("create table batch_attempts (id integer primary key)"))

        run_migrations(engine)

        with engine.connect() as connection:
            run_columns = {
                row[1] for row in connection.execute(text("pragma table_info(test_runs)"))
            }
            batch_columns = {
                row[1] for row in connection.execute(text("pragma table_info(test_batches)"))
            }
            antenna_columns = {
                row[1] for row in connection.execute(text("pragma table_info(antenna_profiles)"))
            }
            attempt_columns = {
                row[1] for row in connection.execute(text("pragma table_info(batch_attempts)"))
            }
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()

        assert "protocol_hash" in run_columns
        assert "expected_protocol_hash" in batch_columns
        assert "unknown_gain_reason" in antenna_columns
        assert "environment_snapshot_hash" in attempt_columns
        assert revision == "20260722_0001"
