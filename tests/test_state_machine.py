from threading import Event

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
from ltap_testbench.profiles.schemas import ServerProfileConfig, TestPlanConfig
from ltap_testbench.profiles.service import create_server_profile, create_test_plan
from ltap_testbench.testnode.client import TestNodeReservation
from ltap_testbench.traffic.tcp_upload import TcpTimedUploadResult


class ConfirmingTestNodeClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def create_reservation(
        self,
        owner: str,
        run_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> TestNodeReservation:
        return TestNodeReservation("res-test", owner, run_id, ttl_seconds)

    def release_reservation(self, _reservation_id: str) -> None:
        return None

    def run_connections(self, run_id: str) -> list[dict]:
        return [
            {
                "run_id": run_id,
                "bytes_received": 1024,
                "duration_seconds": 1.0,
                "average_mbit_s": 0.008,
                "source": "127.0.0.1",
            }
        ]


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


def test_tcp_upload_stage_invokes_timed_sender(monkeypatch) -> None:
    calls = []

    def fake_timed_upload(
        host: str,
        port: int,
        path: str,
        duration_seconds: int,
        chunk_bytes: int = 64 * 1024,
        should_cancel=None,
    ) -> TcpTimedUploadResult:
        calls.append((host, port, path, duration_seconds, chunk_bytes, should_cancel))
        return TcpTimedUploadResult(host, port, path, duration_seconds, 1.0, 1024, 0.008, "")

    monkeypatch.setattr("ltap_testbench.jobs.engine.run_timed_tcp_upload", fake_timed_upload)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://127.0.0.1:8088",
                public_host="198.51.100.10",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig(
                slug="tcp-only",
                name="TCP Only",
                server_slug="stockbot",
                stages=["preflight", "path-verification", "tcp-upload"],
                tcp_upload={"duration_seconds": 1},
            ),
        )

        run = create_run(session, "demo-fake-ltap", "tcp-only")
        run = execute_run(session, run, client_factory=ConfirmingTestNodeClient)

        assert calls
        assert len(run.summary["upload_results"]) == 2
        assert {row["validity"] for row in run.summary["upload_results"]} == {
            "server-confirmed"
        }


def test_cancel_created_run() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run = request_cancel(session, run)
        assert run.state == RunState.CANCELLED


def test_cancel_active_state_requests_worker_stop() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")
        run.state = RunState.PREFLIGHT
        session.add(run)
        session.commit()

        run = request_cancel(session, run)

        assert run.state == RunState.CANCEL_REQUESTED


def test_execute_run_honors_cancel_event() -> None:
    cancel_event = Event()
    cancel_event.set()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-generic", "quick-check")

        run = execute_run(session, run, cancel_event=cancel_event)

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
