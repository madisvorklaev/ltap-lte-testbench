from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RouterKind, RouterProfile, RunState
from ltap_testbench.jobs.engine import (
    create_run,
    execute_run,
    recover_incomplete_runs,
    request_cancel,
)
from ltap_testbench.profiles.defaults import seed_demo_data


def test_fake_run_completes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-fake-ltap", "quick-check")
        run = execute_run(session, run)
        assert run.state == RunState.COMPLETED
        assert run.events


def test_generic_run_completes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run = execute_run(session, run)
        assert run.state == RunState.COMPLETED


def test_cancel_created_run() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run = request_cancel(session, run)
        assert run.state == RunState.CANCELLED


def test_recover_running_run_requires_manual_recovery() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run.state = RunState.RUNNING
        session.add(run)
        session.commit()
        recovered = recover_incomplete_runs(session)
        assert [item.run_id for item in recovered] == [run.run_id]
        assert recovered[0].state == RunState.RECOVERY_REQUIRED


def test_fasttrack_enabled_preflight_fails() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        session.add(
            RouterProfile(
                slug="fake-fasttrack",
                display_name="Fake FastTrack Enabled",
                kind=RouterKind.FAKE,
                metadata_json={"scenario": "fasttrack-enabled", "paths": [{"id": "lte1"}]},
            )
        )
        session.commit()
        run = create_run(session, "fake-fasttrack", "quick-check")
        run = execute_run(session, run)
        assert run.state == RunState.FAILED
        assert run.state_reason == "router preflight failed"


def test_wrong_path_verification_fails() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        session.add(
            RouterProfile(
                slug="fake-wrong-path",
                display_name="Fake Wrong Path",
                kind=RouterKind.FAKE,
                metadata_json={"scenario": "wrong-path", "paths": [{"id": "lte1"}]},
            )
        )
        session.commit()
        run = create_run(session, "fake-wrong-path", "quick-check")
        run = execute_run(session, run)
        assert run.state == RunState.FAILED
        assert run.state_reason == "path verification failed"


def test_api_timeout_fails_with_event() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        session.add(
            RouterProfile(
                slug="fake-api-timeout",
                display_name="Fake API Timeout",
                kind=RouterKind.FAKE,
                metadata_json={"scenario": "api-timeout", "paths": [{"id": "lte1"}]},
            )
        )
        session.commit()
        run = create_run(session, "fake-api-timeout", "quick-check")
        run = execute_run(session, run)
        assert run.state == RunState.FAILED
        assert "Simulated RouterOS API timeout" in (run.state_reason or "")
