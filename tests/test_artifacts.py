import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.core.config import get_settings
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RunState
from ltap_testbench.jobs.engine import create_run, execute_run
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.reporting.artifacts import persist_run_artifacts, run_artifact_dir


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
    assert "## TCP Upload Results" in report
    assert "## UDP Upload Results" in report
    assert "## Latency Results" in report
    assert "## LTE Telemetry" in report
    assert "## Event Timeline" in report
    report_json = json.loads((tmp_path / run.run_id / "report.json").read_text())
    assert report_json["run_id"] == run.run_id
    assert report_json["events"]


def test_execute_run_artifacts_reflect_final_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LTAP_TESTBENCH_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with session_factory() as session:
            seed_demo_data(session)
            run = create_run(session, "demo-generic", "quick-check")
            run = execute_run(session, run)
            artifact_dir = run_artifact_dir(run)

        metadata = json.loads((artifact_dir / "metadata.json").read_text())
        report_json = json.loads((artifact_dir / "report.json").read_text())
        event_types = [event["type"] for event in report_json["events"]]

        assert run.state == RunState.COMPLETED
        assert metadata["state"] == RunState.COMPLETED
        assert report_json["state"] == RunState.COMPLETED
        assert "state" in event_types
    finally:
        get_settings.cache_clear()
