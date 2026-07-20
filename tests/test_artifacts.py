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
    assert "report_markdown" in artifacts
    assert "report_json" in artifacts
    assert (tmp_path / run.run_id / "events.jsonl").read_text()
    report = (tmp_path / run.run_id / "report.md").read_text()
    assert f"# LtAP Test Run {run.run_id}" in report
    assert "## Event Timeline" in report
    report_json = json.loads((tmp_path / run.run_id / "report.json").read_text())
    assert report_json["run_id"] == run.run_id
    assert report_json["events"]
