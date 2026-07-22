from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from alembic import command
from ltap_testbench.core.config import get_settings


class Base(DeclarativeBase):
    pass


def engine_from_settings() -> Engine:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(settings.database_url, future=True)


ENGINE = engine_from_settings()
SessionLocal = sessionmaker(bind=ENGINE, class_=Session, expire_on_commit=False, future=True)


def init_db() -> None:
    from ltap_testbench.db import models  # noqa: F401

    run_migrations(ENGINE)


def run_migrations(engine: Engine = ENGINE) -> None:
    from ltap_testbench.db import models  # noqa: F401

    if _is_in_memory_sqlite(engine):
        Base.metadata.create_all(bind=engine)
        return
    if _needs_legacy_sqlite_stamp(engine):
        Base.metadata.create_all(bind=engine)
        _migrate_sqlite(engine)
        _stamp_alembic_head(engine)
        return
    _upgrade_alembic(engine)


def _alembic_config(engine: Engine) -> Config:
    project_root = Path(__file__).resolve().parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", str(engine.url))
    return config


def _upgrade_alembic(engine: Engine) -> None:
    command.upgrade(_alembic_config(engine), "head")


def _stamp_alembic_head(engine: Engine) -> None:
    command.stamp(_alembic_config(engine), "head")


def _is_in_memory_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite" and engine.url.database in {None, "", ":memory:"}


def _needs_legacy_sqlite_stamp(engine: Engine) -> bool:
    if engine.dialect.name != "sqlite":
        return False
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    return bool(table_names - {"alembic_version"}) and "alembic_version" not in table_names


def _migrate_sqlite(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    run_columns = {
        "benchmark_protocol_id": "INTEGER",
        "protocol_hash": "VARCHAR(64)",
        "result_schema_version": "INTEGER DEFAULT 1",
        "experiment_id": "INTEGER",
        "variant_id": "INTEGER",
        "batch_id": "VARCHAR(80)",
        "batch_attempt_id": "INTEGER",
        "comparison_eligible": "BOOLEAN DEFAULT 0",
        "exclusion_reasons_json": "JSON DEFAULT '[]'",
        "environment_snapshot_json": "JSON DEFAULT '{}'",
        "environment_snapshot_hash": "VARCHAR(64)",
        "integrity_json": "JSON DEFAULT '{}'",
        "application_version": "VARCHAR(80)",
        "application_git_commit": "VARCHAR(80)",
        "test_node_version": "VARCHAR(80)",
    }
    batch_columns = {
        "protocol_id": "INTEGER",
        "experiment_id": "INTEGER",
        "variant_id": "INTEGER",
        "site_id": "INTEGER",
        "start_after": "DATETIME",
        "max_runtime_seconds": "INTEGER",
        "expected_application_version": "VARCHAR(80)",
        "expected_application_git_commit": "VARCHAR(80)",
        "expected_test_node_version": "VARCHAR(80)",
        "expected_protocol_hash": "VARCHAR(64)",
        "expected_variant_snapshot_hash": "VARCHAR(64)",
        "test_profile_id": "INTEGER",
        "test_profile_slug": "VARCHAR(80)",
        "test_profile_version": "VARCHAR(40)",
        "resolved_profile_snapshot_json": "JSON DEFAULT '{}'",
        "target_mode": "VARCHAR(40)",
        "requested_target_value": "FLOAT",
        "requested_target_unit": "VARCHAR(40)",
        "planned_stream_seconds": "INTEGER",
        "estimated_minimum_wall_seconds": "INTEGER",
        "estimated_worst_case_wall_seconds": "INTEGER",
        "worker_id": "VARCHAR(120)",
        "last_heartbeat_at": "DATETIME",
    }
    antenna_columns = {
        "unknown_gain_reason": "TEXT DEFAULT ''",
    }
    attempt_columns = {
        "environment_snapshot_hash": "VARCHAR(64)",
    }
    with engine.begin() as connection:
        existing = {
            row[1] for row in connection.execute(text("PRAGMA table_info(test_runs)")).fetchall()
        }
        for name, definition in run_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE test_runs ADD COLUMN {name} {definition}"))
        existing_batches = {
            row[1] for row in connection.execute(text("PRAGMA table_info(test_batches)")).fetchall()
        }
        for name, definition in batch_columns.items():
            if name not in existing_batches:
                connection.execute(text(f"ALTER TABLE test_batches ADD COLUMN {name} {definition}"))
        existing_antennas = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(antenna_profiles)")).fetchall()
        }
        for name, definition in antenna_columns.items():
            if name not in existing_antennas:
                connection.execute(
                    text(f"ALTER TABLE antenna_profiles ADD COLUMN {name} {definition}")
                )
        existing_attempts = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(batch_attempts)")).fetchall()
        }
        for name, definition in attempt_columns.items():
            if name not in existing_attempts:
                connection.execute(
                    text(f"ALTER TABLE batch_attempts ADD COLUMN {name} {definition}")
                )
        table_names = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        if "test_profiles" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE test_profiles (
                        id INTEGER NOT NULL PRIMARY KEY,
                        slug VARCHAR(80) NOT NULL UNIQUE,
                        name VARCHAR(160) NOT NULL,
                        description TEXT NOT NULL,
                        protocol_id INTEGER NOT NULL,
                        protocol_hash VARCHAR(64) NOT NULL,
                        profile_version VARCHAR(40) NOT NULL,
                        is_comparable BOOLEAN NOT NULL,
                        is_default BOOLEAN NOT NULL,
                        display_order INTEGER NOT NULL,
                        default_target_mode VARCHAR(40) NOT NULL,
                        default_target_value FLOAT NOT NULL,
                        default_inter_run_cooldown_seconds INTEGER NOT NULL,
                        default_max_consecutive_failures INTEGER NOT NULL,
                        created_at DATETIME NOT NULL,
                        retired_at DATETIME
                    )
                    """
                )
            )


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
