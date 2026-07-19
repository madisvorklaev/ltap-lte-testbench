from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RunState
from ltap_testbench.jobs.engine import create_run, execute_run
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
