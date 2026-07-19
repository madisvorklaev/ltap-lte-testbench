import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.profiles.schemas import (
    RouterKindValue,
    RouterPathConfig,
    RouterProfileConfig,
    ServerProfileConfig,
    TestPlanConfig,
)
from ltap_testbench.profiles.service import (
    create_router_profile,
    create_server_profile,
    create_test_plan,
)


def test_create_router_profile_persists_paths() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        router = create_router_profile(
            session,
            RouterProfileConfig(
                slug="api-router",
                display_name="API Router",
                kind=RouterKindValue.FAKE,
                paths=[RouterPathConfig(id="lte1")],
            ),
        )
        assert router.slug == "api-router"
        assert router.metadata_json["paths"][0]["id"] == "lte1"


def test_create_router_profile_rejects_duplicate_slug() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    config = RouterProfileConfig(
        slug="dupe-router",
        display_name="Dupe Router",
        kind=RouterKindValue.FAKE,
    )
    with session_factory() as session:
        create_router_profile(session, config)
        with pytest.raises(ValueError):
            create_router_profile(session, config)


def test_create_test_plan_rejects_duplicate_slug() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    config = TestPlanConfig(slug="dupe-plan", name="Dupe Plan", stages=["preflight"])
    with session_factory() as session:
        create_test_plan(session, config)
        with pytest.raises(ValueError):
            create_test_plan(session, config)


def test_create_server_profile() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        server = create_server_profile(
            session,
            ServerProfileConfig(
                slug="local-node",
                display_name="Local Node",
                control_api_url="http://127.0.0.1:8788",
            ),
        )
        assert server.slug == "local-node"
        assert server.control_api_url == "http://127.0.0.1:8788"
