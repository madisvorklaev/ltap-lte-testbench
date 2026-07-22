import time
from typing import ClassVar

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RunEvent, RunState, ServerProfile
from ltap_testbench.jobs.engine import (
    _execute_udp_upload_stage,
    _execute_video_probe_stage,
    _reservation_renew_interval_seconds,
    _test_node_version,
    create_run,
    execute_run,
)
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.profiles.schemas import ServerProfileConfig, TestPlanConfig
from ltap_testbench.profiles.service import create_server_profile, create_test_plan
from ltap_testbench.testnode.client import TestNodeReservation
from ltap_testbench.traffic.tcp_upload import TcpTimedUploadResult
from ltap_testbench.traffic.udp_upload import UdpUploadResult
from ltap_testbench.traffic.video_udp import VideoUdpProbeResult


class RecordingTestNodeClient:
    created: ClassVar[list[tuple[str, str | None, int]]] = []
    released: ClassVar[list[str]] = []

    def __init__(self, base_url: str):
        self.base_url = base_url

    def create_reservation(
        self,
        owner: str,
        run_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> TestNodeReservation:
        self.created.append((owner, run_id, ttl_seconds))
        return TestNodeReservation(
            id="res-test",
            owner=owner,
            run_id=run_id,
            ttl_seconds=ttl_seconds,
        )

    def release_reservation(self, reservation_id: str) -> None:
        self.released.append(reservation_id)


def test_engine_accepts_legacy_stockbot_health_service_as_version() -> None:
    assert _test_node_version({"version": "stockbot-v1", "service": "stockbot-testnode"}) == (
        "stockbot-v1"
    )
    assert _test_node_version({"service": "stockbot-testnode"}) == "stockbot-testnode"
    assert _test_node_version({}) is None


class FailingRenewalTestNodeClient(RecordingTestNodeClient):
    renewed: ClassVar[list[str]] = []

    def renew_reservation(self, reservation_id: str, ttl_seconds: int | None = None) -> dict:
        self.renewed.append(reservation_id)
        raise RuntimeError("renewal failed")

    def run_connections(self, _run_id: str) -> list[dict]:
        return []


class ReceiverRecordingTestNodeClient:
    requested_run_ids: ClassVar[list[str]] = []

    def run_connections(self, run_id: str) -> list[dict]:
        self.requested_run_ids.append(run_id)
        return [
            {
                "protocol": "udp",
                "bytes_received": 1200,
                "unique_datagrams": 1,
                "datagrams_received": 1,
                "duration_seconds": 1.0,
                "delivered_mbit_s": 0.0096,
                "intervals": [{"offset_seconds": 0, "bytes": 1200}],
            }
        ]

    def video_frame_stats(
        self,
        run_id: str,
        finalize: bool = False,
        delete: bool = False,
    ) -> dict:
        self.requested_run_ids.append(run_id)
        return {
            "paths": {
                "lte1": {"datagrams_received": 10, "frames_seen": 9, "frames_complete": 8},
                "lte2": {"datagrams_received": 10, "frames_seen": 9, "frames_complete": 7},
            },
            "dual_path": {
                "paths": ["lte1", "lte2"],
                "complete_on_both": 7,
                "complete_on_either": 8,
                "lte1_only_complete": 1,
                "lte2_only_complete": 0,
                "complete_frame_ids_by_path": {
                    "lte1": [0, 1, 2, 3, 4, 5, 6, 7],
                    "lte2": [0, 1, 2, 3, 4, 5, 6],
                },
            },
        }


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_execute_run_reserves_and_releases_configured_test_node(session_factory) -> None:
    RecordingTestNodeClient.created = []
    RecordingTestNodeClient.released = []
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://192.168.71.8:8088",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig(
                slug="with-server",
                name="With Server",
                server_slug="stockbot",
                stages=["preflight", "path-verification"],
            ),
        )

        run = create_run(session, "demo-generic", "with-server")
        execute_run(session, run, client_factory=RecordingTestNodeClient)

        assert RecordingTestNodeClient.created == [("ltap-testbench", run.run_id, 600)]
        assert RecordingTestNodeClient.released == ["res-test"]
        assert run.summary["test_node_reserved"] is True

        events = session.scalars(select(RunEvent).order_by(RunEvent.id)).all()
        event_types = [event.event_type for event in events]
        assert "server-reservation" in event_types
        assert "server-release" in event_types


def test_reservation_renew_interval_uses_ttl_third_with_caps() -> None:
    assert _reservation_renew_interval_seconds(3) == 1
    assert _reservation_renew_interval_seconds(900) == 300
    assert _reservation_renew_interval_seconds(3600) == 300


def test_execute_run_marks_reservation_lost_when_renewal_fails(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    RecordingTestNodeClient.created = []
    RecordingTestNodeClient.released = []
    FailingRenewalTestNodeClient.renewed = []
    monkeypatch.setattr(
        "ltap_testbench.jobs.engine._reservation_renew_interval_seconds", lambda _ttl: 0.01
    )

    def fake_timed_upload(
        host: str,
        port: int,
        path: str,
        duration_seconds: int,
        chunk_bytes: int = 64 * 1024,
        should_cancel=None,
        token: str | None = None,
    ) -> TcpTimedUploadResult:
        deadline = time.monotonic() + 1
        while should_cancel is not None and not should_cancel():
            if time.monotonic() > deadline:
                break
            time.sleep(0.005)
        return TcpTimedUploadResult(host, port, path, duration_seconds, 0.05, 0, 0.0, "")

    monkeypatch.setattr("ltap_testbench.jobs.engine.run_timed_tcp_upload", fake_timed_upload)
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://192.0.2.10:8088",
                public_host="198.51.100.10",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig.model_validate(
                {
                    "slug": "renewal-fails",
                    "name": "Renewal Fails",
                    "server_slug": "stockbot",
                    "stages": ["preflight", "path-verification", "tcp-upload"],
                    "tcp_upload": {"duration_seconds": 30},
                }
            ),
        )

        run = create_run(session, "demo-fake-ltap", "renewal-fails")
        run = execute_run(session, run, client_factory=FailingRenewalTestNodeClient)

        assert run.state == RunState.FAILED
        assert run.state_reason == "RESERVATION_LOST"
        assert run.comparison_eligible is False
        assert run.exclusion_reasons_json == ["RESERVATION_LOST"]
        assert run.integrity_json["reservation_valid_entire_run"] is False
        assert run.summary["reservation_renewals"][0]["ok"] is False
        assert FailingRenewalTestNodeClient.renewed == ["res-test"]
        assert RecordingTestNodeClient.released == ["res-test"]


def test_udp_stage_uses_reserved_test_node_client_for_receiver_results(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    ReceiverRecordingTestNodeClient.requested_run_ids = []

    def fake_udp_upload(
        host: str,
        port: int,
        duration_seconds: int,
        bitrate_mbit_s: float,
        datagram_bytes: int = 1200,
        run_id: str | None = None,
        token: str | None = None,
        should_cancel=None,
    ) -> UdpUploadResult:
        assert token == "tok-test"
        assert run_id in {"run-udp-lte1-udp-end", "run-udp-lte2-udp-end"}
        return UdpUploadResult(
            target_host=host,
            target_port=port,
            duration_seconds=1.0,
            requested_duration_seconds=duration_seconds,
            bitrate_mbit_s=bitrate_mbit_s,
            datagram_bytes=datagram_bytes,
            datagrams_sent=1,
            bytes_sent=datagram_bytes,
            average_mbit_s=datagram_bytes * 8 / 1_000_000,
        )

    monkeypatch.setattr("ltap_testbench.jobs.engine.run_udp_upload", fake_udp_upload)
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://192.0.2.10:8088",
                public_host="198.51.100.10",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig.model_validate(
                {
                    "slug": "udp-stage",
                    "name": "UDP Stage",
                    "server_slug": "stockbot",
                    "stages": ["udp-upload"],
                    "udp_upload": {
                        "duration_seconds": 1,
                        "bitrate_mbit_s": 1,
                        "datagram_bytes": 1200,
                    },
                }
            ),
        )
        run = create_run(session, "demo-fake-ltap", "udp-stage")
        run.run_id = "run-udp"
        session.add(run)
        session.commit()

        rows = _execute_udp_upload_stage(
            session,
            run,
            session.scalar(select(ServerProfile).where(ServerProfile.slug == "stockbot")),
            ReceiverRecordingTestNodeClient(),
            reservation_token="tok-test",
        )

        assert sorted(ReceiverRecordingTestNodeClient.requested_run_ids) == [
            "run-udp-lte1-udp-end",
            "run-udp-lte2-udp-end",
        ]
        assert {row["validity"] for row in rows} == {"server-confirmed"}
        assert {row["receiver"]["unique_datagrams"] for row in rows} == {1}


def test_video_stage_reports_both_path_loss_percent(
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    ReceiverRecordingTestNodeClient.requested_run_ids = []

    def fake_video_probe(
        host: str,
        port: int,
        run_id: str,
        path_id: str,
        duration_seconds: int,
        bitrate_mbit_s: float,
        fps: int = 25,
        resolution: str = "1080p",
        scenario: str = "city",
        payload_bytes: int = 1200,
        traffic_seed: str = "video-trace-v1",
        trace_id: str = "synthetic-city-v1",
        generator_version: str = "synthetic-video-v2",
        token: str | None = None,
        should_cancel=None,
    ) -> VideoUdpProbeResult:
        assert token == "tok-video"
        return VideoUdpProbeResult(
            target_host=host,
            target_port=port,
            run_id=run_id,
            path_id=path_id,
            resolution=resolution,
            scenario=scenario,
            duration_seconds=1.0,
            requested_duration_seconds=duration_seconds,
            bitrate_mbit_s=bitrate_mbit_s,
            fps=fps,
            payload_bytes=payload_bytes,
            traffic_seed=traffic_seed,
            trace_id=trace_id,
            generator_version=generator_version,
            frames_sent=10,
            datagrams_sent=10,
            bytes_sent=10 * payload_bytes,
            average_mbit_s=10 * payload_bytes * 8 / 1_000_000,
            first_send_ns=1,
            last_send_ns=2,
        )

    monkeypatch.setattr("ltap_testbench.jobs.engine.run_video_udp_probe", fake_video_probe)
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://192.0.2.10:8088",
                public_host="198.51.100.10",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig.model_validate(
                {
                    "slug": "video-stage",
                    "name": "Video Stage",
                    "server_slug": "stockbot",
                    "stages": ["video-udp-probe"],
                    "video_probe": {
                        "enabled": True,
                        "duration_seconds": 1,
                        "bitrate_mbit_s": 1,
                        "receiver_settle_seconds": 0,
                    },
                }
            ),
        )
        run = create_run(session, "demo-fake-ltap", "video-stage")
        run.run_id = "run-video"
        session.add(run)
        session.commit()

        result = _execute_video_probe_stage(
            session,
            run,
            session.scalar(select(ServerProfile).where(ServerProfile.slug == "stockbot")),
            ReceiverRecordingTestNodeClient(),
            reservation_token="tok-video",
        )

        assert ReceiverRecordingTestNodeClient.requested_run_ids == ["run-video-video"]
        assert result["dual_path"]["frames_sent"] == 10
        assert result["dual_path"]["lost_on_both"] == 2
        assert result["dual_path"]["both_path_loss_percent"] == 20.0
        assert result["dual_path"]["effective_redundant_success_percent"] == 80.0
        assert result["dual_path"]["longest_consecutive_both_lost_frames"] == 2
        assert result["dual_path"]["longest_both_path_outage_seconds"] == 0.08
        assert result["dual_path"]["buckets"][0]["frames_expected"] == 10
        assert result["dual_path"]["buckets"][0]["either_complete"] == 8
        assert result["dual_path"]["buckets"][0]["both_lost"] == 2
