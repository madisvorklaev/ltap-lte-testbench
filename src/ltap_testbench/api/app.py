import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench import __version__
from ltap_testbench.analytics import analytics_run_row, cohort_summary, lab_metadata
from ltap_testbench.benchmarks.defaults import protocol_duration_seconds, seed_benchmark_protocols
from ltap_testbench.db.base import SessionLocal, get_session, init_db
from ltap_testbench.db.models import (
    AntennaProfile,
    BatchAttempt,
    BatchState,
    BenchmarkProtocol,
    GainSource,
    RouterProfile,
    RunState,
    ServerProfile,
    TestBatch,
    TestPlan,
    TestRun,
)
from ltap_testbench.jobs.batch_runner import recover_interrupted_batches, run_batch
from ltap_testbench.jobs.engine import add_event, create_run, execute_run, request_cancel
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.profiles.protocols import (
    COMPARABLE_PROTOCOL_ID,
    COMPARABLE_PROTOCOL_VERSION,
    estimated_duration_seconds,
    protocol_metadata,
)
from ltap_testbench.profiles.schemas import RouterProfileConfig, ServerProfileConfig, TestPlanConfig
from ltap_testbench.profiles.service import (
    create_router_profile,
    create_server_profile,
    create_test_plan,
)
from ltap_testbench.reporting.artifacts import list_run_artifacts, run_artifact_dir
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight
from ltap_testbench.testnode.client import TestNodeClient

template_dir = Path(__file__).resolve().parents[1] / "web" / "templates"
templates = Jinja2Templates(directory=str(template_dir))


class RunCreate(BaseModel):
    router_slug: str
    plan_slug: str = "quick-check"
    execute_now: bool = True


class LabRunCreate(BaseModel):
    router_ip: str = "192.168.101.254"
    benchmark_profile: str = "custom"
    tcp_mode: str = "payload"
    tcp_file_size_mb: int = 25
    tcp_upload_count: int = 1
    tcp_duration_seconds: int = 120
    udp_duration_seconds: int = 60
    udp_bitrate_mbit_s: float = 5.0
    udp_pattern: str = "end"
    video_duration_seconds: int | None = None
    video_resolution: str = "1080p"
    video_fps: int = 25
    video_scenario: str = "city"
    antenna: str = ""
    antenna_gain_dbi: float | None = None
    antenna_gain_source: str = "unknown"
    antenna_cable_loss_db: float | None = None
    antenna_connector_loss_db: float | None = None
    antenna_mounting: str = ""
    antenna_orientation: str = ""
    notes: str = ""


class AntennaProfileCreate(BaseModel):
    slug: str
    manufacturer: str
    model: str
    antenna_type: str = "mimo"
    mimo_port_count: int = 2
    gain_source: str = "unknown"
    nominal_peak_gain_dbi: float | None = None
    gain_by_band: list[dict[str, Any]] = Field(default_factory=list)
    cable_type: str = ""
    cable_length_m: float = 0.0
    estimated_cable_loss_db: float | None = None
    connector_loss_db: float | None = None
    mounting_location: str = ""
    orientation: str = ""
    notes: str = ""


class TestBatchCreate(BaseModel):
    name: str
    protocol_slug: str = "comparable-v1"
    router_slug: str = "r1-ltap-live"
    antenna_profile_id: int | None = None
    target_valid_runs: int = 10
    max_attempts: int = 15
    inter_run_cooldown_seconds: int = 120
    retry_delay_seconds: int = 300
    max_consecutive_failures: int = 3
    deadline: str | None = None
    notes: str = ""


class LabRecoveryError(RuntimeError):
    pass


LAB_LOCK = Lock()
LAB_ACTIVE_RUN_ID: str | None = None
LAB_CANCEL_EVENTS: dict[str, Event] = {}
BATCH_CANCEL_EVENTS: dict[str, Event] = {}
LAB_LIVE_LATENCY_CACHE: dict[str, Any] = {"run_id": None, "timestamp": 0.0, "results": []}
LAB_RESERVATION_OWNER = "ltap-testbench"
TCP_FILE_SIZE_OPTIONS_MB = [5, 10, 25, 50, 100]
TERMINAL_RUN_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
    RunState.INTERRUPTED,
    RunState.RECOVERY_REQUIRED,
}


app = FastAPI(title="LtAP LTE Testbench", version=__version__)


def _antenna_options(session: Session) -> list[str]:
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(100)).all()
    seen = []
    for run in runs:
        lab = run.resolved_plan.get("metadata", {}).get("lab", {}) if run.resolved_plan else {}
        if not lab and run.resolved_plan:
            lab = run.resolved_plan.get("lab", {})
        value = lab.get("antenna")
        if value and value not in seen:
            seen.append(value)
    return seen[:20]


def _stockbot(session: Session) -> ServerProfile:
    server = session.scalar(select(ServerProfile).where(ServerProfile.slug == "stockbot"))
    if server is None:
        raise ValueError("stockbot server profile is missing")
    return server


def _lab_router(session: Session, router_ip: str) -> RouterProfile:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == "r1-ltap-live"))
    if router is None:
        raise ValueError("r1-ltap-live router profile is missing")
    router.management_host = router_ip
    router.expected_gateway = router_ip
    router.controller_interface = "eno1"
    session.add(router)
    session.commit()
    return router


def _antenna_profile_id(payload: LabRunCreate) -> str:
    value = payload.antenna.strip().lower()
    normalized = "".join(ch if ch.isalnum() else "-" for ch in value).strip("-")
    return normalized or "unknown"


def _antenna_effective_gain(payload: LabRunCreate) -> float | None:
    if payload.antenna_gain_dbi is None:
        return None
    cable_loss = payload.antenna_cable_loss_db or 0.0
    connector_loss = payload.antenna_connector_loss_db or 0.0
    return payload.antenna_gain_dbi - cable_loss - connector_loss


def _protocol_row(protocol: BenchmarkProtocol) -> dict[str, Any]:
    return {
        "id": protocol.id,
        "slug": protocol.slug,
        "version": protocol.version,
        "name": protocol.name,
        "protocol_hash": protocol.protocol_hash,
        "result_schema_version": protocol.result_schema_version,
        "status": protocol.status.value,
        "estimated_attempt_seconds": protocol_duration_seconds(protocol.definition_json),
        "definition": protocol.definition_json,
    }


def _antenna_row(profile: AntennaProfile) -> dict[str, Any]:
    effective_gain = (
        profile.nominal_peak_gain_dbi
        - (profile.estimated_cable_loss_db or 0.0)
        - (profile.connector_loss_db or 0.0)
        if profile.nominal_peak_gain_dbi is not None
        else None
    )
    return {
        "id": profile.id,
        "slug": profile.slug,
        "manufacturer": profile.manufacturer,
        "model": profile.model,
        "antenna_type": profile.antenna_type,
        "mimo_port_count": profile.mimo_port_count,
        "gain_source": profile.gain_source.value,
        "nominal_peak_gain_dbi": profile.nominal_peak_gain_dbi,
        "effective_gain_dbi": effective_gain,
        "gain_by_band": profile.gain_by_band_json,
        "cable_type": profile.cable_type,
        "cable_length_m": profile.cable_length_m,
        "estimated_cable_loss_db": profile.estimated_cable_loss_db,
        "connector_loss_db": profile.connector_loss_db,
        "mounting_location": profile.mounting_location,
        "orientation": profile.orientation,
        "notes": profile.notes,
    }


def _batch_row(batch: TestBatch, protocol: BenchmarkProtocol | None = None) -> dict[str, Any]:
    estimated_attempt_seconds = (
        protocol_duration_seconds(protocol.definition_json) if protocol is not None else 0
    )
    estimated_cycle_seconds = estimated_attempt_seconds + batch.inter_run_cooldown_seconds
    return {
        "batch_id": batch.batch_id,
        "name": batch.name,
        "state": batch.state.value,
        "protocol_slug": batch.protocol_slug,
        "protocol_hash": batch.protocol_hash,
        "router_slug": batch.router_slug,
        "antenna_profile_id": batch.antenna_profile_id,
        "target_valid_runs": batch.target_valid_runs,
        "max_attempts": batch.max_attempts,
        "valid_run_count": batch.valid_run_count,
        "attempt_count": batch.attempt_count,
        "invalid_run_count": batch.invalid_run_count,
        "failed_attempt_count": batch.failed_attempt_count,
        "consecutive_failure_count": batch.consecutive_failure_count,
        "inter_run_cooldown_seconds": batch.inter_run_cooldown_seconds,
        "estimated_attempt_seconds": estimated_attempt_seconds,
        "estimated_cycle_seconds": estimated_cycle_seconds,
        "deadline": batch.deadline.isoformat() if batch.deadline else None,
        "state_reason": batch.state_reason,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }


def _upsert_lab_plan(session: Session, payload: LabRunCreate) -> TestPlan:
    benchmark_profile = payload.benchmark_profile
    tcp_mode = payload.tcp_mode
    tcp_count = payload.tcp_upload_count
    tcp_duration = payload.tcp_duration_seconds
    tcp_bytes = payload.tcp_file_size_mb * 1024 * 1024 if tcp_mode == "payload" else None
    udp_duration = payload.udp_duration_seconds
    udp_bitrate = payload.udp_bitrate_mbit_s
    udp_pattern = payload.udp_pattern
    video_duration = payload.video_duration_seconds or payload.udp_duration_seconds
    video_bitrate = payload.udp_bitrate_mbit_s
    video_fps = payload.video_fps
    protocol_id = "exploratory-lab"
    protocol_version = "1"
    if benchmark_profile == "comparable-v1":
        protocol_id = COMPARABLE_PROTOCOL_ID
        protocol_version = COMPARABLE_PROTOCOL_VERSION
        tcp_mode = "timed"
        tcp_count = 3
        tcp_duration = 60
        tcp_bytes = None
        udp_duration = 120
        udp_bitrate = 5.0
        udp_pattern = "end"
        video_duration = 300
        video_bitrate = 5.0
        video_fps = 25
    definition: dict[str, Any] = {
        "slug": "lab-current",
        "name": "Current Lab Test",
        "version": "1",
        "protocol_id": protocol_id,
        "protocol_version": protocol_version,
        "result_schema_version": 2,
        "server_slug": "stockbot",
        "stages": [
            "preflight",
            "path-verification",
            "idle-latency",
            "tcp-upload",
            "udp-upload",
            "video-udp-probe",
        ],
        "latency": {"duration_seconds": 10, "interval_ms": 1000},
        "tcp_upload": {
            "duration_seconds": tcp_duration,
            "parallel_streams": [1],
            "payload_bytes": tcp_bytes,
            "count": tcp_count,
        },
        "udp_upload": {
            "duration_seconds": udp_duration,
            "bitrate_mbit_s": udp_bitrate,
            "datagram_bytes": 1200,
            "pattern": udp_pattern,
        },
        "video_probe": {
            "enabled": True,
            "resolution": payload.video_resolution,
            "scenario": payload.video_scenario,
            "duration_seconds": video_duration,
            "bitrate_mbit_s": video_bitrate,
            "fps": video_fps,
            "payload_bytes": 1200,
            "receiver_settle_seconds": 5,
            "traffic_seed": "video-trace-v1",
            "trace_id": f"synthetic-{payload.video_scenario}-v1",
            "generator_version": "synthetic-video-v2",
        },
        "traffic": {"path_concurrency": "parallel"},
        "telemetry": {"controller_interval_seconds": 1, "lte_interval_seconds": 5},
        "temporary_router_changes": {"disable_fasttrack": False, "clear_test_connections": True},
        "metadata": {
            "protocol": {
                "profile": benchmark_profile,
                "tcp_mode": tcp_mode,
                "estimated_duration_seconds": 0,
            },
            "lab": {
                "router_ip": payload.router_ip,
                "benchmark_profile": benchmark_profile,
                "tcp_mode": tcp_mode,
                "tcp_file_size_mb": payload.tcp_file_size_mb,
                "tcp_upload_count": tcp_count,
                "tcp_duration_seconds": tcp_duration,
                "udp_duration_seconds": udp_duration,
                "udp_bitrate_mbit_s": udp_bitrate,
                "udp_pattern": udp_pattern,
                "video_duration_seconds": video_duration,
                "video_resolution": payload.video_resolution,
                "video_fps": video_fps,
                "video_scenario": payload.video_scenario,
                "antenna": payload.antenna,
                "antenna_profile_id": _antenna_profile_id(payload),
                "antenna_gain_dbi": payload.antenna_gain_dbi,
                "antenna_gain_source": payload.antenna_gain_source,
                "antenna_cable_loss_db": payload.antenna_cable_loss_db,
                "antenna_connector_loss_db": payload.antenna_connector_loss_db,
                "antenna_effective_gain_dbi": _antenna_effective_gain(payload),
                "antenna_mounting": payload.antenna_mounting,
                "antenna_orientation": payload.antenna_orientation,
                "notes": payload.notes,
            },
        },
    }
    definition = TestPlanConfig.model_validate(definition).model_dump(mode="json")
    metadata = definition.setdefault("metadata", {})
    protocol = metadata.setdefault("protocol", {})
    if isinstance(protocol, dict):
        protocol.update(protocol_metadata(definition))
        protocol["estimated_duration_seconds"] = estimated_duration_seconds(definition)
    plan = session.scalar(select(TestPlan).where(TestPlan.slug == "lab-current"))
    if plan is None:
        plan = TestPlan(
            slug="lab-current", name="Current Lab Test", version="1", definition=definition
        )
    else:
        plan.name = "Current Lab Test"
        plan.definition = definition
    session.add(plan)
    session.commit()
    return plan


def _recover_orphaned_lab_reservations(session: Session) -> None:
    if LAB_ACTIVE_RUN_ID is not None:
        return
    try:
        server = _stockbot(session)
        client = TestNodeClient(server.control_api_url)
        status = client.status()
    except Exception:
        return
    reserved_lab_run_ids = set()
    failures = []
    for reservation in status.get("active_reservations", []):
        if reservation.get("owner") != LAB_RESERVATION_OWNER:
            continue
        reservation_id = reservation.get("id")
        run_id = reservation.get("run_id")
        if not reservation_id:
            continue
        run = (
            session.scalar(select(TestRun).where(TestRun.run_id == str(run_id)))
            if run_id
            else None
        )
        if run is not None and run.plan_slug == "lab-current":
            reserved_lab_run_ids.add(str(run_id))
        if (
            run is not None
            and run.plan_slug != "lab-current"
            and run.state not in TERMINAL_RUN_STATES
        ):
            continue
        try:
            client.release_reservation(str(reservation_id))
        except Exception as exc:
            failures.append(str(reservation_id))
            if run is not None and run.plan_slug == "lab-current":
                run.state = RunState.RECOVERY_REQUIRED
                run.state_reason = "failed to release orphaned lab reservation"
                add_event(
                    session,
                    run,
                    "server-release-failed",
                    "Failed to release orphaned lab reservation.",
                    {
                        "reservation_id": reservation_id,
                        "type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            continue
        if (
            run is not None
            and run.plan_slug == "lab-current"
            and run.state not in TERMINAL_RUN_STATES
        ):
            run.state = RunState.INTERRUPTED
            run.state_reason = "interrupted by web service restart"
            add_event(
                session,
                run,
                "server-release",
                "Released orphaned lab reservation after worker restart.",
                {"reservation_id": reservation_id},
            )
            session.add(run)
    stale_lab_runs = session.scalars(
        select(TestRun).where(
            TestRun.plan_slug == "lab-current",
            TestRun.state.not_in(TERMINAL_RUN_STATES),
        )
    ).all()
    for run in stale_lab_runs:
        if run.run_id in reserved_lab_run_ids:
            continue
        run.state = RunState.INTERRUPTED
        run.state_reason = "interrupted by web service restart"
        add_event(
            session,
            run,
            "lab-worker-recovery",
            "Marked orphaned lab run interrupted after worker restart.",
        )
        session.add(run)
    session.commit()
    if failures:
        raise LabRecoveryError(
            "failed to release orphaned lab reservation(s): " + ", ".join(failures)
        )


def _run_lab_background(run_id: str, cancel_event: Event) -> None:
    global LAB_ACTIVE_RUN_ID
    try:
        with SessionLocal() as session:
            run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
            if run is None:
                return
            execute_run(session, run, cancel_event=cancel_event)
    finally:
        with LAB_LOCK:
            if run_id == LAB_ACTIVE_RUN_ID:
                LAB_ACTIVE_RUN_ID = None
            LAB_CANCEL_EVENTS.pop(run_id, None)


def _run_batch_background(batch_id: str, cancel_event: Event) -> None:
    try:
        with SessionLocal() as session:
            batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
            if batch is None:
                return
            run_batch(session, batch, cancel_event=cancel_event)
    finally:
        BATCH_CANCEL_EVENTS.pop(batch_id, None)


def _latest_lab_run(session: Session) -> TestRun | None:
    if LAB_ACTIVE_RUN_ID:
        run = session.scalar(select(TestRun).where(TestRun.run_id == LAB_ACTIVE_RUN_ID))
        if run is not None:
            return run
    return session.scalar(select(TestRun).order_by(TestRun.id.desc()))


def _path_ports(run: TestRun) -> dict[str, int]:
    paths = run.router.metadata_json.get("paths", []) if run.router.metadata_json else []
    ports = {}
    for path in paths:
        path_id = path.get("id")
        port = path.get("ports", {}).get("start")
        if path_id and port:
            ports[str(path_id)] = int(port)
    return ports


def _tcp_upload_count(run: TestRun) -> int:
    tcp_config = run.resolved_plan.get("tcp_upload", {}) if run.resolved_plan else {}
    try:
        return max(1, int(tcp_config.get("count", 1)))
    except (TypeError, ValueError):
        return 1


def _udp_labels(run: TestRun) -> list[str]:
    udp_config = run.resolved_plan.get("udp_upload", {}) if run.resolved_plan else {}
    pattern = str(udp_config.get("pattern", "end"))
    if pattern == "beginning":
        return ["beginning"]
    if pattern == "after_each_tcp":
        return [f"after-tcp-{index}" for index in range(1, _tcp_upload_count(run) + 1)]
    return ["end"]


def _connections_for(client: TestNodeClient, run_id: str) -> list[dict]:
    try:
        return client.run_connections(run_id)
    except Exception:
        return []


def _sum_connection_bytes(connections: list[dict]) -> int:
    return sum(int(connection.get("bytes_received") or 0) for connection in connections)


def _sum_connection_duration(connections: list[dict]) -> float:
    return sum(float(connection.get("duration_seconds") or 0) for connection in connections)


def _mbit_s(byte_count: int, duration_seconds: float) -> float | None:
    if duration_seconds <= 0:
        return None
    return byte_count * 8 / duration_seconds / 1_000_000


def _current_phase_info(run: TestRun) -> dict[str, Any]:
    for event in reversed(run.events):
        if event.event_type == "video-probe-stage-started":
            return {
                "name": "video",
                "duration_seconds": event.details.get("duration_seconds"),
                "bitrate_mbit_s": event.details.get("bitrate_mbit_s"),
            }
        if event.event_type == "udp-upload-stage-started":
            return {"name": "udp", "label": event.details.get("label", "end")}
        if event.event_type == "upload-stage-started":
            return {"name": "tcp", "round": int(event.details.get("round", 1))}
        if event.event_type == "latency-stage":
            return {"name": "latency"}
        if event.event_type == "path-verification":
            return {"name": "path verification"}
        if event.event_type == "router-preflight":
            return {"name": "preflight"}
    return {"name": "setup"}


def _live_lab_metrics(session: Session, run: TestRun) -> dict:
    paths = _path_ports(run)
    path_metrics_by_id: dict[str, dict[str, Any]] = {
        path_id: {
            "tcp_uploaded_mb": 0.0,
            "udp_uploaded_mb": 0.0,
            "phase_uploaded_mb": 0.0,
            "tcp_average_mbit_s": None,
            "udp_average_mbit_s": None,
        }
        for path_id in paths
    }
    metrics = {
        "current_phase": _current_phase_info(run),
        "paths": path_metrics_by_id,
    }
    if not paths:
        return metrics
    try:
        client = TestNodeClient(_stockbot(session).control_api_url)
    except Exception:
        return metrics
    phase = metrics["current_phase"]
    phase_name = str(phase.get("name", "setup"))
    phase_round = int(phase.get("round", 1))
    phase_label = str(phase.get("label", "end"))
    tcp_count = _tcp_upload_count(run)
    udp_labels = _udp_labels(run)
    for path_id in paths:
        tcp_connections = [
            connection
            for round_index in range(1, tcp_count + 1)
            for connection in _connections_for(client, f"{run.run_id}-{path_id}-tcp{round_index}")
        ]
        udp_connections = [
            connection
            for label in udp_labels
            for connection in _connections_for(client, f"{run.run_id}-{path_id}-udp-{label}")
        ]
        tcp_bytes = _sum_connection_bytes(tcp_connections)
        udp_bytes = _sum_connection_bytes(udp_connections)
        phase_connections = []
        if phase_name == "tcp":
            phase_connections = _connections_for(client, f"{run.run_id}-{path_id}-tcp{phase_round}")
        elif phase_name == "udp":
            phase_connections = _connections_for(
                client, f"{run.run_id}-{path_id}-udp-{phase_label}"
            )
        phase_bytes = _sum_connection_bytes(phase_connections)
        tcp_duration = _sum_connection_duration(tcp_connections)
        udp_duration = _sum_connection_duration(udp_connections)
        path_metrics = path_metrics_by_id[path_id]
        path_metrics["tcp_uploaded_mb"] = round(tcp_bytes / 1024 / 1024, 2)
        path_metrics["udp_uploaded_mb"] = round(udp_bytes / 1024 / 1024, 2)
        path_metrics["phase_uploaded_mb"] = round(phase_bytes / 1024 / 1024, 2)
        path_metrics["tcp_average_mbit_s"] = _mbit_s(tcp_bytes, tcp_duration)
        path_metrics["udp_average_mbit_s"] = _mbit_s(udp_bytes, udp_duration)
    if phase_name == "video":
        try:
            metrics["video_probe"] = client.video_frame_stats(f"{run.run_id}-video")
        except Exception:
            metrics["video_probe"] = {}
        for path_id, row in (metrics.get("video_probe", {}).get("paths") or {}).items():
            if path_id in path_metrics_by_id:
                bytes_received = row.get("bytes_received") or 0
                path_metrics_by_id[path_id]["phase_uploaded_mb"] = round(
                    float(bytes_received) / 1024 / 1024,
                    2,
                )
    return metrics


def _live_latency_results(session: Session, run: TestRun, adapter: Any) -> list[dict]:
    now = time.monotonic()
    cached_run_id = LAB_LIVE_LATENCY_CACHE.get("run_id")
    cached_at = float(LAB_LIVE_LATENCY_CACHE.get("timestamp") or 0.0)
    if cached_run_id == run.run_id and now - cached_at < 5:
        return list(LAB_LIVE_LATENCY_CACHE.get("results") or [])
    try:
        server = _stockbot(session)
        if not server.public_host:
            return []
        results = adapter.measure_latency(server.public_host, count=1)
    except Exception:
        results = []
    LAB_LIVE_LATENCY_CACHE.update(
        {"run_id": run.run_id, "timestamp": time.monotonic(), "results": results}
    )
    return results


def _float_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _lab_metadata(run: TestRun) -> dict[str, Any]:
    return lab_metadata(run)


def _known_path_ids(run: TestRun) -> list[str]:
    path_ids = []
    for path in run.router.metadata_json.get("paths", []) if run.router.metadata_json else []:
        path_id = path.get("id")
        if path_id:
            path_ids.append(str(path_id))
    for key in ("latency_results", "upload_results", "udp_upload_results"):
        for row in run.summary.get(key, []) if run.summary else []:
            path_id = row.get("path_id")
            if path_id and str(path_id) not in path_ids:
                path_ids.append(str(path_id))
    video_paths = (
        (run.summary.get("video_probe_results") or {}).get("paths", {})
        if run.summary
        else {}
    )
    for path_id in video_paths:
        if str(path_id) not in path_ids:
            path_ids.append(str(path_id))
    return path_ids or ["lte1", "lte2"]


def _analytics_run_row(run: TestRun) -> dict[str, Any]:
    return analytics_run_row(run)


@app.on_event("startup")
def startup() -> None:
    init_db()
    with SessionLocal() as session:
        seed_benchmark_protocols(session)
        recover_interrupted_batches(session)
        with suppress(LabRecoveryError):
            _recover_orphaned_lab_reservations(session)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    routers = session.scalars(select(RouterProfile).order_by(RouterProfile.slug)).all()
    plans = session.scalars(select(TestPlan).order_by(TestPlan.slug)).all()
    servers = session.scalars(select(ServerProfile).order_by(ServerProfile.slug)).all()
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(10)).all()
    protocols = session.scalars(select(BenchmarkProtocol).order_by(BenchmarkProtocol.slug)).all()
    antenna_profiles = session.scalars(select(AntennaProfile).order_by(AntennaProfile.slug)).all()
    batches = session.scalars(select(TestBatch).order_by(TestBatch.id.desc()).limit(10)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "version": __version__,
            "routers": routers,
            "plans": plans,
            "servers": servers,
            "runs": runs,
            "tcp_file_size_options_mb": TCP_FILE_SIZE_OPTIONS_MB,
            "antenna_options": _antenna_options(session),
            "benchmark_protocols": protocols,
            "antenna_profiles": antenna_profiles,
            "batches": batches,
        },
    )


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "version": __version__,
            "antenna_options": _antenna_options(session),
        },
    )


@app.get("/antennas", response_class=HTMLResponse)
def antennas(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "antenna_profiles.html",
        {"version": __version__},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    run_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report_path = run_artifact_dir(run) / "report.md"
    report_markdown = report_path.read_text() if report_path.is_file() else None
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run": run,
            "artifacts": list_run_artifacts(run),
            "report_markdown": report_markdown,
        },
    )


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/v1/benchmark-protocols")
def benchmark_protocols(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    protocols = session.scalars(select(BenchmarkProtocol).order_by(BenchmarkProtocol.slug)).all()
    return [_protocol_row(protocol) for protocol in protocols]


@app.get("/api/v1/benchmark-protocols/{slug}")
def benchmark_protocol(slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    protocol = session.scalar(select(BenchmarkProtocol).where(BenchmarkProtocol.slug == slug))
    if protocol is None:
        raise HTTPException(status_code=404, detail="benchmark protocol not found")
    return _protocol_row(protocol)


@app.get("/api/v1/antenna-profiles")
def antenna_profiles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    profiles = session.scalars(select(AntennaProfile).order_by(AntennaProfile.slug)).all()
    return [_antenna_row(profile) for profile in profiles]


@app.post("/api/v1/antenna-profiles")
def create_antenna_profile(
    payload: AntennaProfileCreate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if payload.mimo_port_count < 1:
        raise HTTPException(status_code=400, detail="mimo_port_count must be positive")
    if payload.cable_length_m < 0:
        raise HTTPException(status_code=400, detail="cable_length_m must be non-negative")
    try:
        gain_source = GainSource(payload.gain_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unsupported gain source") from exc
    if gain_source != GainSource.UNKNOWN and payload.nominal_peak_gain_dbi is None:
        raise HTTPException(status_code=400, detail="numeric gain is required")
    existing = session.scalar(select(AntennaProfile).where(AntennaProfile.slug == payload.slug))
    if existing is not None:
        raise HTTPException(status_code=409, detail="antenna profile already exists")
    profile = AntennaProfile(
        slug=payload.slug,
        manufacturer=payload.manufacturer,
        model=payload.model,
        antenna_type=payload.antenna_type,
        mimo_port_count=payload.mimo_port_count,
        gain_source=gain_source,
        nominal_peak_gain_dbi=payload.nominal_peak_gain_dbi,
        gain_by_band_json=payload.gain_by_band,
        cable_type=payload.cable_type,
        cable_length_m=payload.cable_length_m,
        estimated_cable_loss_db=payload.estimated_cable_loss_db,
        connector_loss_db=payload.connector_loss_db,
        mounting_location=payload.mounting_location,
        orientation=payload.orientation,
        notes=payload.notes,
    )
    session.add(profile)
    session.commit()
    return _antenna_row(profile)


@app.get("/api/v1/test-batches")
def test_batches(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    batches = session.scalars(select(TestBatch).order_by(TestBatch.id.desc()).limit(100)).all()
    protocols = {
        protocol.protocol_hash: protocol
        for protocol in session.scalars(select(BenchmarkProtocol)).all()
    }
    return [_batch_row(batch, protocols.get(batch.protocol_hash)) for batch in batches]


@app.post("/api/v1/test-batches")
def create_test_batch(
    payload: TestBatchCreate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if payload.target_valid_runs < 1:
        raise HTTPException(status_code=400, detail="target_valid_runs must be positive")
    if payload.max_attempts < payload.target_valid_runs:
        raise HTTPException(status_code=400, detail="max_attempts must be >= target_valid_runs")
    if payload.max_consecutive_failures < 1:
        raise HTTPException(status_code=400, detail="max_consecutive_failures must be positive")
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.slug == payload.protocol_slug)
    )
    if protocol is None:
        raise HTTPException(status_code=404, detail="benchmark protocol not found")
    if payload.antenna_profile_id is None:
        raise HTTPException(status_code=400, detail="antenna_profile_id is required")
    antenna = session.get(AntennaProfile, payload.antenna_profile_id)
    if antenna is None:
        raise HTTPException(status_code=404, detail="antenna profile not found")
    deadline = None
    if payload.deadline:
        with suppress(ValueError):
            deadline = datetime.fromisoformat(payload.deadline)
        if deadline is None:
            raise HTTPException(status_code=400, detail="invalid deadline")
    batch = TestBatch(
        batch_id=f"batch-{uuid4().hex[:12]}",
        name=payload.name,
        protocol_slug=protocol.slug,
        protocol_hash=protocol.protocol_hash,
        router_slug=payload.router_slug,
        antenna_profile_id=antenna.id,
        state=BatchState.DRAFT,
        target_valid_runs=payload.target_valid_runs,
        max_attempts=payload.max_attempts,
        inter_run_cooldown_seconds=payload.inter_run_cooldown_seconds,
        retry_delay_seconds=payload.retry_delay_seconds,
        max_consecutive_failures=payload.max_consecutive_failures,
        deadline=deadline,
        notes=payload.notes,
    )
    session.add(batch)
    session.commit()
    return _batch_row(batch, protocol)


@app.get("/api/v1/test-batches/active")
def active_test_batch(session: Session = Depends(get_session)) -> dict[str, Any]:
    batch = session.scalar(
        select(TestBatch)
        .where(
            TestBatch.state.in_(
                [
                    BatchState.RUNNING,
                    BatchState.PAUSE_REQUESTED,
                    BatchState.CANCEL_REQUESTED,
                ]
            )
        )
        .order_by(TestBatch.id.desc())
    )
    if batch is None:
        return {"active": False, "batch": None}
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.protocol_hash == batch.protocol_hash)
    )
    return {"active": True, "batch": _batch_row(batch, protocol)}


@app.get("/api/v1/test-batches/{batch_id}")
def test_batch(batch_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
    if batch is None:
        raise HTTPException(status_code=404, detail="test batch not found")
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.protocol_hash == batch.protocol_hash)
    )
    return _batch_row(batch, protocol)


@app.post("/api/v1/test-batches/{batch_id}/start")
def start_test_batch(batch_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
    if batch is None:
        raise HTTPException(status_code=404, detail="test batch not found")
    if batch.state not in {BatchState.DRAFT, BatchState.SCHEDULED, BatchState.PAUSED}:
        raise HTTPException(status_code=409, detail=f"batch is {batch.state.value}")
    if BATCH_CANCEL_EVENTS:
        raise HTTPException(status_code=409, detail="batch worker is already active")
    active_batch = session.scalar(
        select(TestBatch).where(
            TestBatch.state.in_(
                [
                    BatchState.RUNNING,
                    BatchState.PAUSE_REQUESTED,
                    BatchState.CANCEL_REQUESTED,
                ]
            )
        )
    )
    if active_batch is not None and active_batch.batch_id != batch_id:
        raise HTTPException(status_code=409, detail=f"batch {active_batch.batch_id} is active")
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.protocol_hash == batch.protocol_hash)
    )
    if protocol is None:
        raise HTTPException(status_code=404, detail="benchmark protocol not found")
    cancel_event = Event()
    BATCH_CANCEL_EVENTS[batch_id] = cancel_event
    batch.state = BatchState.RUNNING
    batch.started_at = batch.started_at or datetime.now().astimezone()
    batch.state_reason = None
    session.add(batch)
    session.commit()
    Thread(target=_run_batch_background, args=(batch_id, cancel_event), daemon=True).start()
    return _batch_row(batch, protocol)


@app.post("/api/v1/test-batches/{batch_id}/cancel")
def cancel_test_batch(batch_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
    if batch is None:
        raise HTTPException(status_code=404, detail="test batch not found")
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.protocol_hash == batch.protocol_hash)
    )
    cancel_event = BATCH_CANCEL_EVENTS.get(batch_id)
    if cancel_event is not None:
        cancel_event.set()
    if batch.state not in {
        BatchState.CANCELLED,
        BatchState.COMPLETED,
        BatchState.FAILED,
    }:
        batch.state = BatchState.CANCEL_REQUESTED
        batch.state_reason = "user_cancelled"
        session.add(batch)
        session.commit()
    return _batch_row(batch, protocol)


@app.get("/api/v1/test-batches/{batch_id}/attempts")
def test_batch_attempts(
    batch_id: str,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
    if batch is None:
        raise HTTPException(status_code=404, detail="test batch not found")
    attempts = session.scalars(
        select(BatchAttempt)
        .where(BatchAttempt.batch_pk == batch.id)
        .order_by(BatchAttempt.sequence_number)
    ).all()
    return [
        {
            "sequence_number": attempt.sequence_number,
            "state": attempt.state.value,
            "run_id": attempt.run_id,
            "comparison_eligible": attempt.comparison_eligible,
            "outcome_code": attempt.outcome_code,
            "outcome_details": attempt.outcome_details_json,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
        }
        for attempt in attempts
    ]


@app.get("/api/v1/analytics/runs")
def analytics_runs(
    antenna: str | None = None,
    protocol_hash: str | None = None,
    eligible_only: bool = False,
    state: str = "COMPLETED",
    limit: int = 30,
    session: Session = Depends(get_session),
) -> dict:
    limit = max(1, min(limit, 500))
    normalized_state = state.upper()
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(500)).all()
    rows = []
    antenna_values = []
    protocol_values = []
    for run in runs:
        lab = _lab_metadata(run)
        run_antenna = str(lab.get("antenna") or "")
        if run_antenna and run_antenna not in antenna_values:
            antenna_values.append(run_antenna)
        if antenna is not None and run_antenna != antenna:
            continue
        if normalized_state != "ALL" and run.state.value != normalized_state:
            continue
        row = _analytics_run_row(run)
        run_protocol_hash = str(row.get("protocol_hash") or "")
        if run_protocol_hash and run_protocol_hash not in protocol_values:
            protocol_values.append(run_protocol_hash)
        if protocol_hash and run_protocol_hash != protocol_hash:
            continue
        if eligible_only and not row.get("comparison_eligible"):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    rows.reverse()
    return {
        "filters": {
            "antenna": antenna,
            "protocol_hash": protocol_hash,
            "eligible_only": eligible_only,
            "state": normalized_state,
            "limit": limit,
            "antenna_options": antenna_values[:50],
            "protocol_hash_options": protocol_values[:50],
        },
        "summary": cohort_summary(rows),
        "runs": rows,
    }


@app.get("/api/v1/runs/{run_id}/live")
def run_live(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    events = [
        {
            "timestamp": event.timestamp.isoformat(),
            "type": event.event_type,
            "message": event.message,
            "details": event.details,
        }
        for event in run.events
    ]
    return {
        "active": run.state not in TERMINAL_RUN_STATES,
        "run": {
            "run_id": run.run_id,
            "state": run.state.value,
            "router_name": run.router.display_name,
            "router_ip": run.router.management_host,
            "plan": run.plan_slug,
            "batch_id": run.batch_id,
            "batch_attempt_id": run.batch_attempt_id,
            "protocol_hash": run.protocol_hash,
            "comparison_eligible": run.comparison_eligible,
            "exclusion_reasons": run.exclusion_reasons_json,
            "environment_snapshot_hash": run.environment_snapshot_hash,
            "integrity": run.integrity_json,
            "summary": run.summary,
            "events": events,
            "artifacts": list_run_artifacts(run),
        },
    }


@app.post("/api/v1/lab/start")
def lab_start(payload: LabRunCreate, session: Session = Depends(get_session)) -> dict:
    global LAB_ACTIVE_RUN_ID
    if payload.benchmark_profile not in {"custom", "comparable-v1"}:
        raise HTTPException(status_code=400, detail="unsupported benchmark profile")
    if payload.tcp_mode not in {"payload", "timed"}:
        raise HTTPException(status_code=400, detail="unsupported TCP mode")
    if payload.benchmark_profile == "comparable-v1" and not payload.antenna.strip():
        raise HTTPException(status_code=400, detail="comparable benchmark requires antenna profile")
    if payload.tcp_file_size_mb not in TCP_FILE_SIZE_OPTIONS_MB:
        raise HTTPException(status_code=400, detail="unsupported TCP file size")
    if payload.tcp_upload_count < 1 or payload.tcp_upload_count > 20:
        raise HTTPException(status_code=400, detail="TCP upload count must be 1..20")
    if payload.tcp_duration_seconds < 1 or payload.tcp_duration_seconds > 3600:
        raise HTTPException(status_code=400, detail="TCP duration must be 1..3600 seconds")
    if payload.udp_duration_seconds < 1 or payload.udp_duration_seconds > 3600:
        raise HTTPException(status_code=400, detail="UDP duration must be 1..3600 seconds")
    video_duration = payload.video_duration_seconds or payload.udp_duration_seconds
    if video_duration < 1 or video_duration > 3600:
        raise HTTPException(status_code=400, detail="video duration must be 1..3600 seconds")
    if payload.udp_bitrate_mbit_s <= 0 or payload.udp_bitrate_mbit_s > 50:
        raise HTTPException(status_code=400, detail="UDP bitrate must be 0..50 Mbit/s")
    if payload.udp_pattern not in {"after_each_tcp", "beginning", "end"}:
        raise HTTPException(status_code=400, detail="unsupported UDP pattern")
    if payload.video_resolution not in {"720p", "1080p", "1440p", "4k"}:
        raise HTTPException(status_code=400, detail="unsupported video resolution")
    if payload.video_fps not in {25, 30, 50}:
        raise HTTPException(status_code=400, detail="unsupported video FPS")
    if payload.video_scenario not in {"parked", "city", "highway", "rough-road"}:
        raise HTTPException(status_code=400, detail="unsupported video scenario")
    try:
        with LAB_LOCK:
            active_run_id = LAB_ACTIVE_RUN_ID
            if active_run_id:
                active_run = session.scalar(select(TestRun).where(TestRun.run_id == active_run_id))
                active = active_run is None or active_run.state not in TERMINAL_RUN_STATES
                if active:
                    raise HTTPException(
                        status_code=409,
                        detail=f"lab run {active_run_id} is already active",
                    )
                LAB_ACTIVE_RUN_ID = None
            _lab_router(session, payload.router_ip)
            _stockbot(session)
            _recover_orphaned_lab_reservations(session)
            _upsert_lab_plan(session, payload)
            run = create_run(session, "r1-ltap-live", "lab-current")
            cancel_event = Event()
            LAB_ACTIVE_RUN_ID = run.run_id
            LAB_CANCEL_EVENTS[run.run_id] = cancel_event
    except HTTPException:
        raise
    except LabRecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        with LAB_LOCK:
            previous_active_run_id = active_run_id if "active_run_id" in locals() else None
            if LAB_ACTIVE_RUN_ID not in {None, previous_active_run_id}:
                LAB_ACTIVE_RUN_ID = None
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        Thread(target=_run_lab_background, args=(run.run_id, cancel_event), daemon=True).start()
    except Exception:
        with LAB_LOCK:
            if run.run_id == LAB_ACTIVE_RUN_ID:
                LAB_ACTIVE_RUN_ID = None
            LAB_CANCEL_EVENTS.pop(run.run_id, None)
        raise
    return {"run_id": run.run_id, "state": run.state, "plan": run.resolved_plan}


@app.get("/api/v1/lab/status")
def lab_status(session: Session = Depends(get_session)) -> dict:
    run = _latest_lab_run(session)
    if run is None:
        return {"active": False, "run": None}
    active = run.state not in TERMINAL_RUN_STATES
    adapter = adapter_for(run.router)
    telemetry = []
    if active:
        try:
            telemetry = adapter.collect_path_telemetry()
        except Exception:
            telemetry = []
    live_metrics = _live_lab_metrics(session, run) if active else {}
    if active:
        live_metrics["latency_results"] = _live_latency_results(session, run, adapter)
    events = [
        {
            "timestamp": event.timestamp.isoformat(),
            "type": event.event_type,
            "message": event.message,
            "details": event.details,
        }
        for event in run.events
    ]
    return {
        "active": active,
        "run": {
            "run_id": run.run_id,
            "state": run.state,
            "router_name": run.router.display_name,
            "router_ip": run.router.management_host,
            "plan": run.plan_slug,
            "description": run.resolved_plan.get("metadata", {}).get("lab", {})
            or run.resolved_plan.get("lab", {}),
            "summary": run.summary,
            "events": events,
            "telemetry": telemetry,
            "live_metrics": live_metrics,
            "artifacts": list_run_artifacts(run),
        },
    }


@app.post("/api/v1/demo/seed")
def seed_demo(session: Session = Depends(get_session)) -> dict:
    seed_demo_data(session)
    return {"ok": True}


@app.get("/api/v1/routers")
def list_routers(session: Session = Depends(get_session)) -> list[dict]:
    routers = session.scalars(select(RouterProfile).order_by(RouterProfile.slug)).all()
    return [
        {
            "id": router.id,
            "slug": router.slug,
            "display_name": router.display_name,
            "kind": router.kind,
            "management_host": router.management_host,
            "allow_configuration_changes": router.allow_configuration_changes,
        }
        for router in routers
    ]


@app.post("/api/v1/routers")
def api_create_router(
    payload: RouterProfileConfig,
    session: Session = Depends(get_session),
) -> dict:
    try:
        router = create_router_profile(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": router.id,
        "slug": router.slug,
        "display_name": router.display_name,
        "kind": router.kind,
    }


@app.post("/api/v1/routers/{router_slug}/preflight")
def api_preflight_router(router_slug: str, session: Session = Depends(get_session)) -> dict:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        raise HTTPException(status_code=404, detail="router not found")
    controller = common_preflight(router.controller_interface)
    checks = adapter_for(router).preflight()
    return {
        "controller": controller.to_dict(),
        "router": [
            {
                "name": check.name,
                "ok": check.ok,
                "message": check.message,
                "details": check.details,
            }
            for check in checks
        ],
    }


@app.get("/api/v1/test-plans")
def list_test_plans(session: Session = Depends(get_session)) -> list[dict]:
    plans = session.scalars(select(TestPlan).order_by(TestPlan.slug)).all()
    return [
        {
            "slug": plan.slug,
            "name": plan.name,
            "version": plan.version,
            "definition": plan.definition,
        }
        for plan in plans
    ]


@app.post("/api/v1/test-plans")
def api_create_test_plan(
    payload: TestPlanConfig,
    session: Session = Depends(get_session),
) -> dict:
    try:
        plan = create_test_plan(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": plan.id,
        "slug": plan.slug,
        "name": plan.name,
        "version": plan.version,
    }


@app.get("/api/v1/servers")
def list_servers(session: Session = Depends(get_session)) -> list[dict]:
    servers = session.scalars(select(ServerProfile).order_by(ServerProfile.slug)).all()
    return [
        {
            "id": server.id,
            "slug": server.slug,
            "display_name": server.display_name,
            "control_api_url": server.control_api_url,
            "public_host": server.public_host,
        }
        for server in servers
    ]


@app.post("/api/v1/servers")
def api_create_server(
    payload: ServerProfileConfig,
    session: Session = Depends(get_session),
) -> dict:
    try:
        server = create_server_profile(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": server.id,
        "slug": server.slug,
        "display_name": server.display_name,
        "control_api_url": server.control_api_url,
    }


@app.post("/api/v1/servers/{server_slug}/health")
def server_health(server_slug: str, session: Session = Depends(get_session)) -> dict:
    server = session.scalar(select(ServerProfile).where(ServerProfile.slug == server_slug))
    if server is None:
        raise HTTPException(status_code=404, detail="server not found")
    client = TestNodeClient(server.control_api_url)
    try:
        return client.health()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"test-node health check failed: {exc}",
        ) from exc


@app.post("/api/v1/runs")
def api_create_run(payload: RunCreate, session: Session = Depends(get_session)) -> dict:
    try:
        run = create_run(session, payload.router_slug, payload.plan_slug)
        if payload.execute_now:
            run = execute_run(session, run)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": run.run_id, "state": run.state, "summary": run.summary}


@app.get("/api/v1/runs")
def list_runs(session: Session = Depends(get_session)) -> list[dict]:
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc())).all()
    return [
        {
            "run_id": run.run_id,
            "router": run.router.slug,
            "plan": run.plan_slug,
            "state": run.state,
        }
        for run in runs
    ]


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run.run_id,
        "router": run.router.slug,
        "plan": run.plan_slug,
        "state": run.state,
        "summary": run.summary,
        "events": [
            {
                "timestamp": event.timestamp.isoformat(),
                "type": event.event_type,
                "message": event.message,
                "details": event.details,
            }
            for event in run.events
        ],
    }


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    with LAB_LOCK:
        cancel_event = LAB_CANCEL_EVENTS.get(run_id)
        if cancel_event is not None:
            cancel_event.set()
    run = request_cancel(session, run)
    return {"run_id": run.run_id, "state": run.state, "reason": run.state_reason}


@app.get("/api/v1/runs/{run_id}/artifacts")
def get_run_artifacts(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return list_run_artifacts(run)


@app.get("/api/v1/runs/{run_id}/artifacts/{relative_path:path}")
def download_run_artifact(
    run_id: str,
    relative_path: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    root = run_artifact_dir(run).resolve()
    target = (root / relative_path).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target)
