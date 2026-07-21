from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.api import app as api_app
from ltap_testbench.api.app import (
    LabRecoveryError,
    LabRunCreate,
    _live_lab_metrics,
    _recover_orphaned_lab_reservations,
    _upsert_lab_plan,
    app,
)
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import (
    RouterKind,
    RouterProfile,
    RunEvent,
    RunState,
    ServerProfile,
)
from ltap_testbench.db.models import (
    TestRun as DbTestRun,
)


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_router_preflight_api() -> None:
    client = TestClient(app)
    client.post("/api/v1/demo/seed")
    response = client.post("/api/v1/routers/demo-generic/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "controller" in payload
    assert payload["router"][0]["ok"] is True


def test_lab_plan_keeps_tcp_count_and_udp_pattern() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        plan = _upsert_lab_plan(
            session,
            LabRunCreate(
                tcp_file_size_mb=5,
                tcp_upload_count=3,
                udp_duration_seconds=4,
                udp_bitrate_mbit_s=5,
                udp_pattern="after_each_tcp",
                video_resolution="1080p",
                video_fps=25,
                video_scenario="city",
                antenna="test placement",
            ),
        )

        assert plan.definition["tcp_upload"]["payload_bytes"] == 5 * 1024 * 1024
        assert plan.definition["tcp_upload"]["count"] == 3
        assert plan.definition["udp_upload"]["duration_seconds"] == 4
        assert plan.definition["udp_upload"]["bitrate_mbit_s"] == 5
        assert plan.definition["udp_upload"]["pattern"] == "after_each_tcp"
        assert "tcp-upload" in plan.definition["stages"]
        assert "short-upload" not in plan.definition["stages"]
        assert plan.definition["video_probe"]["resolution"] == "1080p"
        assert "codec" not in plan.definition["video_probe"]
        assert plan.definition["video_probe"]["fps"] == 25
        assert plan.definition["video_probe"]["scenario"] == "city"
        assert plan.definition["metadata"]["lab"]["antenna"] == "test placement"


def test_live_lab_metrics_use_video_bytes_for_phase_upload(monkeypatch) -> None:
    class FakeTestNodeClient:
        def __init__(self, _base_url: str):
            pass

        def run_connections(self, _run_id: str) -> list[dict]:
            return []

        def video_frame_stats(self, _run_id: str) -> dict:
            return {
                "paths": {
                    "lte1": {"bytes_received": 5 * 1024 * 1024},
                    "lte2": {"bytes_received": 7.5 * 1024 * 1024},
                }
            }

    monkeypatch.setattr(api_app, "TestNodeClient", FakeTestNodeClient)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        router = RouterProfile(
            slug="r1-ltap-live",
            display_name="R1",
            kind=RouterKind.FAKE,
            metadata_json={
                "paths": [
                    {"id": "lte1", "ports": {"start": 5002, "end": 5002}},
                    {"id": "lte2", "ports": {"start": 5022, "end": 5022}},
                ]
            },
        )
        session.add_all(
            [
                router,
                ServerProfile(
                    slug="stockbot",
                    display_name="Stockbot",
                    control_api_url="http://stockbot",
                ),
            ]
        )
        session.flush()
        run = DbTestRun(
            run_id="R0000001",
            router=router,
            plan_slug="lab-current",
            state=RunState.RUNNING,
            resolved_plan={},
            summary={},
        )
        run.events.append(
            RunEvent(
                event_type="video-probe-stage-started",
                message="Video started.",
                details={"duration_seconds": 60, "bitrate_mbit_s": 5},
            )
        )
        session.add(run)
        session.commit()

        metrics = _live_lab_metrics(session, run)

        assert metrics["paths"]["lte1"]["phase_uploaded_mb"] == 5.0
        assert metrics["paths"]["lte2"]["phase_uploaded_mb"] == 7.5


def test_recover_orphaned_lab_reservation_only_releases_owned_lab_run(monkeypatch) -> None:
    released: list[str] = []

    class FakeTestNodeClient:
        def __init__(self, _base_url: str):
            pass

        def status(self) -> dict:
            return {
                "active_reservations": [
                    {
                        "id": "res-lab",
                        "owner": "ltap-testbench",
                        "run_id": "run-lab",
                    },
                    {
                        "id": "res-other",
                        "owner": "other-tool",
                        "run_id": "run-other",
                    },
                ]
            }

        def release_reservation(self, reservation_id: str) -> None:
            released.append(reservation_id)

    monkeypatch.setattr(api_app, "TestNodeClient", FakeTestNodeClient)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        router = RouterProfile(slug="r1-ltap-live", display_name="R1", kind=RouterKind.FAKE)
        session.add_all(
            [
                router,
                ServerProfile(
                    slug="stockbot",
                    display_name="Stockbot",
                    control_api_url="http://stockbot",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                DbTestRun(
                    run_id="run-lab",
                    router=router,
                    plan_slug="lab-current",
                    state=RunState.RUNNING,
                    resolved_plan={},
                    summary={},
                ),
                DbTestRun(
                    run_id="run-other",
                    router=router,
                    plan_slug="other-plan",
                    state=RunState.RUNNING,
                    resolved_plan={},
                    summary={},
                ),
                DbTestRun(
                    run_id="run-orphan-no-reservation",
                    router=router,
                    plan_slug="lab-current",
                    state=RunState.RUNNING,
                    resolved_plan={},
                    summary={},
                ),
            ]
        )
        session.commit()

        _recover_orphaned_lab_reservations(session)

        lab_run = session.scalar(select(DbTestRun).where(DbTestRun.run_id == "run-lab"))
        other_run = session.scalar(select(DbTestRun).where(DbTestRun.run_id == "run-other"))
        orphan_run = session.scalar(
            select(DbTestRun).where(DbTestRun.run_id == "run-orphan-no-reservation")
        )

        assert released == ["res-lab"]
        assert lab_run is not None
        assert lab_run.state == RunState.INTERRUPTED
        assert lab_run.state_reason == "interrupted by web service restart"
        assert other_run is not None
        assert other_run.state == RunState.RUNNING
        assert orphan_run is not None
        assert orphan_run.state == RunState.INTERRUPTED


def test_recover_orphaned_lab_reservation_releases_missing_and_terminal_runs(
    monkeypatch,
) -> None:
    released: list[str] = []

    class FakeTestNodeClient:
        def __init__(self, _base_url: str):
            pass

        def status(self) -> dict:
            return {
                "active_reservations": [
                    {
                        "id": "res-terminal",
                        "owner": "ltap-testbench",
                        "run_id": "run-terminal",
                    },
                    {
                        "id": "res-missing",
                        "owner": "ltap-testbench",
                        "run_id": "run-missing",
                    },
                    {
                        "id": "res-no-run",
                        "owner": "ltap-testbench",
                    },
                ]
            }

        def release_reservation(self, reservation_id: str) -> None:
            released.append(reservation_id)

    monkeypatch.setattr(api_app, "TestNodeClient", FakeTestNodeClient)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        router = RouterProfile(slug="r1-ltap-live", display_name="R1", kind=RouterKind.FAKE)
        session.add_all(
            [
                router,
                ServerProfile(
                    slug="stockbot",
                    display_name="Stockbot",
                    control_api_url="http://stockbot",
                ),
            ]
        )
        session.flush()
        session.add(
            DbTestRun(
                run_id="run-terminal",
                router=router,
                plan_slug="lab-current",
                state=RunState.COMPLETED,
                resolved_plan={},
                summary={},
            )
        )
        session.commit()

        _recover_orphaned_lab_reservations(session)

        assert released == ["res-terminal", "res-missing", "res-no-run"]


def test_recover_orphaned_lab_reservation_failure_marks_recovery_required(
    monkeypatch,
) -> None:
    class FakeTestNodeClient:
        def __init__(self, _base_url: str):
            pass

        def status(self) -> dict:
            return {
                "active_reservations": [
                    {
                        "id": "res-lab",
                        "owner": "ltap-testbench",
                        "run_id": "run-lab",
                    },
                ]
            }

        def release_reservation(self, _reservation_id: str) -> None:
            raise RuntimeError("stockbot delete failed")

    monkeypatch.setattr(api_app, "TestNodeClient", FakeTestNodeClient)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        router = RouterProfile(slug="r1-ltap-live", display_name="R1", kind=RouterKind.FAKE)
        session.add_all(
            [
                router,
                ServerProfile(
                    slug="stockbot",
                    display_name="Stockbot",
                    control_api_url="http://stockbot",
                ),
            ]
        )
        session.flush()
        session.add(
            DbTestRun(
                run_id="run-lab",
                router=router,
                plan_slug="lab-current",
                state=RunState.RUNNING,
                resolved_plan={},
                summary={},
            )
        )
        session.commit()

        try:
            _recover_orphaned_lab_reservations(session)
        except LabRecoveryError:
            pass
        else:
            raise AssertionError("expected LabRecoveryError")

        lab_run = session.scalar(select(DbTestRun).where(DbTestRun.run_id == "run-lab"))
        assert lab_run is not None
        assert lab_run.state == RunState.RECOVERY_REQUIRED
