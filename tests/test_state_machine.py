from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RunState
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
