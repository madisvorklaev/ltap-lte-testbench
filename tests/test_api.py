from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ltap_testbench.analytics import cohort_summary
from ltap_testbench.api import app as api_app
from ltap_testbench.api.app import (
    LAB_LIVE_LATENCY_CACHE,
    LabRecoveryError,
    LabRunCreate,
    _analytics_run_row,
    _live_lab_metrics,
    _live_latency_results,
    _recover_orphaned_lab_reservations,
    _upsert_lab_plan,
    app,
)
from ltap_testbench.benchmarks.defaults import seed_benchmark_protocols
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import (
    BatchState,
    MetricSample,
    RouterKind,
    RouterProfile,
    RunEvent,
    RunState,
    ServerProfile,
    TestBatch,
)
from ltap_testbench.db.models import (
    TestRun as DbTestRun,
)
from ltap_testbench.profiles.defaults import seed_demo_data


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
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
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
        assert plan.definition["metadata"]["protocol"]["protocol_hash"]


def test_comparable_lab_plan_uses_fixed_protocol_and_requires_antenna() -> None:
    client = TestClient(app)
    client.post("/api/v1/demo/seed")

    missing = client.post("/api/v1/lab/start", json={"benchmark_profile": "comparable-v1"})

    assert missing.status_code == 400
    assert "antenna" in missing.json()["detail"]

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        plan = _upsert_lab_plan(
            session,
            LabRunCreate(
                benchmark_profile="comparable-v1",
                antenna="roof panel",
                antenna_gain_dbi=6.5,
                antenna_cable_loss_db=1.2,
            ),
        )

        assert plan.definition["protocol_id"] == "comparable-benchmark"
        assert plan.definition["tcp_upload"]["payload_bytes"] is None
        assert plan.definition["tcp_upload"]["duration_seconds"] == 60
        assert plan.definition["tcp_upload"]["count"] == 3
        assert plan.definition["udp_upload"]["duration_seconds"] == 120
        assert plan.definition["video_probe"]["duration_seconds"] == 300
        assert plan.definition["metadata"]["lab"]["antenna_effective_gain_dbi"] == 5.3


def test_analytics_run_row_extracts_path_metrics() -> None:
    router = RouterProfile(
        slug="r1-ltap-live",
        display_name="R1",
        kind=RouterKind.FAKE,
        metadata_json={"paths": [{"id": "lte1"}, {"id": "lte2"}]},
    )
    run = DbTestRun(
        run_id="run-analytics",
        router=router,
        plan_slug="lab-current",
        state=RunState.COMPLETED,
        resolved_plan={
            "metadata": {
                "lab": {
                    "antenna": "window panel",
                    "tcp_upload_count": 2,
                    "udp_bitrate_mbit_s": 5,
                }
            }
        },
        summary={
            "validity": "live-upload",
            "latency_results": [
                {"path_id": "lte1", "avg_ms": 24.0, "loss_percent": 0.0},
                {"path_id": "lte2", "avg_ms": 36.0, "loss_percent": 1.0},
            ],
            "upload_results": [
                {"path_id": "lte1", "server_average_mbit_s": 40.0},
                {"path_id": "lte1", "server_average_mbit_s": 50.0},
                {"path_id": "lte2", "server_average_mbit_s": 30.0},
            ],
            "udp_upload_results": [
                {
                    "path_id": "lte1",
                    "average_mbit_s": 5.0,
                    "receiver": {"delivered_mbit_s": 4.8},
                    "delivery": {"packet_loss_percent": 4.0},
                },
                {
                    "path_id": "lte2",
                    "average_mbit_s": 5.0,
                    "test_node_connections": [
                        {"protocol": "udp", "average_mbit_s": 4.4},
                    ],
                },
            ],
            "video_probe_results": {
                "paths": {
                    "lte1": {"frame_success_percent": 98.0, "frames_not_decodable": 2},
                    "lte2": {"frame_success_percent": 94.0, "frames_not_decodable": 6},
                }
            },
        },
    )

    row = _analytics_run_row(run)

    assert row["antenna"] == "window panel"
    assert row["paths"]["lte1"]["tcp_mbit_s"] == 45.0
    assert row["paths"]["lte2"]["udp_mbit_s"] == 4.4
    assert row["paths"]["lte1"]["udp_loss_percent"] == 4.0
    assert row["paths"]["lte1"]["latency_avg_ms"] == 24.0
    assert row["paths"]["lte2"]["video_success_percent"] == 94.0


def test_cohort_summary_flags_mixed_protocols() -> None:
    rows = [
        {"protocol_hash": "aaa", "comparison_eligible": True, "paths": {}},
        {"protocol_hash": "bbb", "comparison_eligible": True, "paths": {}},
    ]

    summary = cohort_summary(rows)

    assert summary["mixed_protocols"] is True
    assert summary["minimum_evidence_met"] is False
    assert summary["conclusion"]["status"] == "INCONCLUSIVE"
    assert "multiple protocol" in summary["conclusion"]["reason"]


def test_cohort_summary_requires_minimum_evidence_and_reports_variability() -> None:
    rows = [
        {
            "protocol_hash": "aaa",
            "comparison_eligible": True,
            "paths": {"lte1": {"tcp_mbit_s": value}},
        }
        for value in [10, 20, 30, 40, 50]
    ]

    summary = cohort_summary(rows)

    assert summary["minimum_evidence_met"] is True
    assert summary["conclusion"]["status"] == "INCONCLUSIVE"
    assert "baseline and candidate" in summary["conclusion"]["reason"]
    assert summary["metrics"]["lte1"]["tcp_mbit_s"]["n"] == 5
    assert summary["metrics"]["lte1"]["tcp_mbit_s"]["median"] == 30
    assert summary["metrics"]["lte1"]["tcp_mbit_s"]["p25"] == 20
    assert summary["metrics"]["lte1"]["tcp_mbit_s"]["p75"] == 40


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


def test_live_latency_results_are_cached() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def measure_latency(self, target_host: str, count: int = 5) -> list[dict]:
            self.calls += 1
            return [
                {
                    "path_id": "lte1",
                    "target_host": target_host,
                    "sent": count,
                    "received": count,
                    "avg_ms": 24.0,
                }
            ]

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    LAB_LIVE_LATENCY_CACHE.update({"run_id": None, "timestamp": 0.0, "results": []})
    with session_factory() as session:
        router = RouterProfile(slug="r1-ltap-live", display_name="R1", kind=RouterKind.FAKE)
        session.add_all(
            [
                router,
                ServerProfile(
                    slug="stockbot",
                    display_name="Stockbot",
                    control_api_url="http://stockbot",
                    public_host="198.51.100.10",
                ),
            ]
        )
        session.flush()
        run = DbTestRun(
            run_id="run-live",
            router=router,
            plan_slug="lab-current",
            state=RunState.RUNNING,
            resolved_plan={},
            summary={},
        )
        session.add(run)
        session.commit()
        adapter = FakeAdapter()

        first = _live_latency_results(session, run, adapter)
        second = _live_latency_results(session, run, adapter)

        assert first == second
        assert first[0]["avg_ms"] == 24.0
        assert adapter.calls == 1


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


def test_protocol_antenna_and_batch_api_use_persistent_models() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        seed_benchmark_protocols(session)

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[api_app.get_session] = override_session
    try:
        client = TestClient(app)

        protocols = client.get("/api/v1/benchmark-protocols")
        assert protocols.status_code == 200
        assert {row["slug"] for row in protocols.json()} >= {
            "comparable-v1",
            "video-stability-v1",
        }

        missing_gain = client.post(
            "/api/v1/antenna-profiles",
            json={
                "slug": "bad-gain",
                "manufacturer": "ACME",
                "model": "Panel",
                "gain_source": "manufacturer",
            },
        )
        assert missing_gain.status_code == 400

        antenna = client.post(
            "/api/v1/antenna-profiles",
            json={
                "slug": "roof-panel",
                "manufacturer": "ACME",
                "model": "Panel",
                "gain_source": "manufacturer",
                "nominal_peak_gain_dbi": 7.0,
                "estimated_cable_loss_db": 1.0,
                "connector_loss_db": 0.5,
                "mounting_location": "roof",
                "orientation": "south",
            },
        )
        assert antenna.status_code == 200
        antenna_id = antenna.json()["id"]
        assert antenna.json()["effective_gain_dbi"] == 5.5

        site = client.post(
            "/api/v1/test-sites",
            json={
                "slug": "workshop-window",
                "name": "Workshop window",
                "location_description": "Fixed indoor test location",
                "indoor_outdoor": "indoor",
            },
        )
        assert site.status_code == 200
        site_id = site.json()["id"]

        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "Antenna repeatability",
                "comparison_dimension": "antenna",
                "protocol_slug": "comparable-v1",
                "site_id": site_id,
                "primary_metrics": ["tcp_median_mbit_s", "video_either_success_percent"],
            },
        )
        assert experiment.status_code == 200
        experiment_id = experiment.json()["id"]
        assert experiment.json()["protocol_slug"] == "comparable-v1"

        variant = client.post(
            f"/api/v1/experiments/{experiment_id}/variants",
            json={
                "label": "roof panel",
                "antenna_mapping": {"lte1": antenna_id, "lte2": antenna_id},
            },
        )
        assert variant.status_code == 200
        variant_id = variant.json()["id"]

        experiment_detail = client.get(f"/api/v1/experiments/{experiment_id}")
        assert experiment_detail.status_code == 200
        assert experiment_detail.json()["variants"][0]["id"] == variant_id

        bad_batch = client.post(
            "/api/v1/test-batches",
            json={
                "name": "Bad batch",
                "antenna_profile_id": antenna_id,
                "target_valid_runs": 10,
                "max_attempts": 5,
            },
        )
        assert bad_batch.status_code == 400

        batch = client.post(
            "/api/v1/test-batches",
            json={
                "name": "Overnight baseline",
                "experiment_id": experiment_id,
                "variant_id": variant_id,
                "antenna_profile_id": antenna_id,
                "target_valid_runs": 5,
                "max_attempts": 7,
            },
        )
        assert batch.status_code == 200
        payload = batch.json()
        assert payload["batch_id"].startswith("batch-")
        assert payload["state"] == "DRAFT"
        assert payload["target_valid_runs"] == 5
        assert payload["max_attempts"] == 7
        assert payload["experiment_id"] == experiment_id
        assert payload["variant_id"] == variant_id
        assert payload["site_id"] == site_id
        assert payload["estimated_attempt_seconds"] > 900

        active = client.get("/api/v1/test-batches/active")
        assert active.status_code == 200
        assert active.json()["active"] is False

        with session_factory() as session:
            stored_batch = session.scalar(
                select(TestBatch).where(TestBatch.batch_id == payload["batch_id"])
            )
            assert stored_batch is not None
            stored_batch.state = BatchState.RUNNING
            session.add(stored_batch)
            session.commit()

        active = client.get("/api/v1/test-batches/active")
        assert active.status_code == 200
        assert active.json()["active"] is True
        assert active.json()["batch"]["batch_id"] == payload["batch_id"]

        with session_factory() as session:
            router = session.scalar(
                select(RouterProfile).where(RouterProfile.slug == "demo-generic")
            )
            assert router is not None
            run = DbTestRun(
                run_id="run-live",
                router_id=router.id,
                plan_slug="quick-check",
                state=RunState.COMPLETED,
                protocol_hash="aaa",
                comparison_eligible=True,
                summary={"comparison_eligible": True},
                environment_snapshot_hash="hash-live",
            )
            session.add(run)
            session.flush()
            session.add_all(
                [
                    MetricSample(
                        run_pk=run.id,
                        offset_ms=1000,
                        path_id="lte1",
                        phase="tcp",
                        metric_name="latency_rtt_ms",
                        value=42.0,
                        unit="ms",
                    ),
                    MetricSample(
                        run_pk=run.id,
                        offset_ms=2000,
                        path_id="lte2",
                        phase="tcp",
                        metric_name="latency_rtt_ms",
                        value=55.0,
                        unit="ms",
                    ),
                ]
            )
            session.commit()

        timeseries = client.get(
            "/api/v1/analytics/timeseries",
            params={"run_id": "run-live", "path_id": "lte1", "metric_name": "latency_rtt_ms"},
        )
        assert timeseries.status_code == 200
        assert len(timeseries.json()["samples"]) == 1
        assert timeseries.json()["samples"][0]["value"] == 42.0

        live = client.get("/api/v1/runs/run-live/live")
        assert live.status_code == 200
        assert live.json()["active"] is False
        assert live.json()["run"]["environment_snapshot_hash"] == "hash-live"
        assert len(live.json()["run"]["recent_metric_samples"]) == 2

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Test Series" in dashboard.text
        assert "batch-table" in dashboard.text
        assert "Create Series" in dashboard.text

        antennas_page = client.get("/antennas")
        assert antennas_page.status_code == 200
        assert "Antenna Profiles" in antennas_page.text
        assert "Create Profile" in antennas_page.text
    finally:
        app.dependency_overrides.clear()
