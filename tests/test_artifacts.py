import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.jobs.engine import create_run, execute_run
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.reporting.artifacts import persist_run_artifacts


def test_run_artifacts_are_written(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run = execute_run(session, run)
        artifacts = persist_run_artifacts(run, tmp_path)

    metadata = json.loads((tmp_path / run.run_id / "metadata.json").read_text())
    assert metadata["run_id"] == run.run_id
    assert "events" in artifacts
    assert (tmp_path / run.run_id / "events.jsonl").read_text()
