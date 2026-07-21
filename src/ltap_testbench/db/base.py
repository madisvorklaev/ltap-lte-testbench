from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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

    Base.metadata.create_all(bind=ENGINE)
    _migrate_sqlite(ENGINE)


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
        "experiment_id": "INTEGER",
        "variant_id": "INTEGER",
        "site_id": "INTEGER",
    }
    with engine.begin() as connection:
        existing = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(test_runs)")).fetchall()
        }
        for name, definition in run_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE test_runs ADD COLUMN {name} {definition}"))
        existing_batches = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(test_batches)")).fetchall()
        }
        for name, definition in batch_columns.items():
            if name not in existing_batches:
                connection.execute(
                    text(f"ALTER TABLE test_batches ADD COLUMN {name} {definition}")
                )


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
