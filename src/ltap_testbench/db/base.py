from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
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


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
