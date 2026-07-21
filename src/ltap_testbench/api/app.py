from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench import __version__
from ltap_testbench.db.base import SessionLocal, get_session, init_db
from ltap_testbench.db.models import RouterProfile, RunState, ServerProfile, TestPlan, TestRun
from ltap_testbench.jobs.engine import create_run, execute_run, request_cancel
from ltap_testbench.profiles.defaults import seed_demo_data
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
    tcp_file_size_mb: int = 25
    tcp_upload_count: int = 1
    udp_duration_seconds: int = 60
    udp_bitrate_mbit_s: float = 5.0
    udp_pattern: str = "end"
    video_resolution: str = "1080p"
    video_fps: int = 25
    video_scenario: str = "city"
    antenna: str = ""


LAB_LOCK = Lock()
LAB_ACTIVE_RUN_ID: str | None = None
LAB_CANCEL_EVENTS: dict[str, Event] = {}
TCP_FILE_SIZE_OPTIONS_MB = [5, 10, 25, 50, 100]


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


def _upsert_lab_plan(session: Session, payload: LabRunCreate) -> TestPlan:
    tcp_bytes = payload.tcp_file_size_mb * 1024 * 1024
    definition = {
        "slug": "lab-current",
        "name": "Current Lab Test",
        "version": "1",
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
            "duration_seconds": 120,
            "parallel_streams": [1],
            "payload_bytes": tcp_bytes,
            "count": payload.tcp_upload_count,
        },
        "udp_upload": {
            "duration_seconds": payload.udp_duration_seconds,
            "bitrate_mbit_s": payload.udp_bitrate_mbit_s,
            "datagram_bytes": 1200,
            "pattern": payload.udp_pattern,
        },
        "video_probe": {
            "enabled": True,
            "resolution": payload.video_resolution,
            "scenario": payload.video_scenario,
            "duration_seconds": payload.udp_duration_seconds,
            "bitrate_mbit_s": payload.udp_bitrate_mbit_s,
            "fps": payload.video_fps,
            "payload_bytes": 1200,
            "receiver_settle_seconds": 5,
        },
        "traffic": {"path_concurrency": "parallel"},
        "telemetry": {"controller_interval_seconds": 1, "lte_interval_seconds": 5},
        "temporary_router_changes": {"disable_fasttrack": False, "clear_test_connections": True},
        "metadata": {
            "lab": {
                "router_ip": payload.router_ip,
                "tcp_file_size_mb": payload.tcp_file_size_mb,
                "tcp_upload_count": payload.tcp_upload_count,
                "udp_duration_seconds": payload.udp_duration_seconds,
                "udp_bitrate_mbit_s": payload.udp_bitrate_mbit_s,
                "udp_pattern": payload.udp_pattern,
                "video_resolution": payload.video_resolution,
                "video_fps": payload.video_fps,
                "video_scenario": payload.video_scenario,
                "antenna": payload.antenna,
            },
        },
    }
    definition = TestPlanConfig.model_validate(definition).model_dump(mode="json")
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


def _clear_lab_reservations(session: Session) -> None:
    try:
        server = _stockbot(session)
        client = TestNodeClient(server.control_api_url)
        status = client.status()
        for reservation in status.get("active_reservations", []):
            reservation_id = reservation.get("id")
            if reservation_id:
                client.release_reservation(reservation_id)
    except Exception:
        pass
    runs = session.scalars(select(TestRun).where(TestRun.state.in_([RunState.RUNNING]))).all()
    for run in runs:
        run.state = RunState.CANCELLED
        run.state_reason = "cleared before lab restart"
        session.add(run)
    session.commit()


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
    return metrics


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    routers = session.scalars(select(RouterProfile).order_by(RouterProfile.slug)).all()
    plans = session.scalars(select(TestPlan).order_by(TestPlan.slug)).all()
    servers = session.scalars(select(ServerProfile).order_by(ServerProfile.slug)).all()
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(10)).all()
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
        },
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


@app.post("/api/v1/lab/start")
def lab_start(payload: LabRunCreate, session: Session = Depends(get_session)) -> dict:
    global LAB_ACTIVE_RUN_ID
    if payload.tcp_file_size_mb not in TCP_FILE_SIZE_OPTIONS_MB:
        raise HTTPException(status_code=400, detail="unsupported TCP file size")
    if payload.tcp_upload_count < 1 or payload.tcp_upload_count > 20:
        raise HTTPException(status_code=400, detail="TCP upload count must be 1..20")
    if payload.udp_duration_seconds < 1 or payload.udp_duration_seconds > 3600:
        raise HTTPException(status_code=400, detail="UDP duration must be 1..3600 seconds")
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
                active = active_run is None or active_run.state not in {
                    RunState.COMPLETED,
                    RunState.FAILED,
                    RunState.CANCELLED,
                    RunState.INTERRUPTED,
                }
                if active:
                    raise HTTPException(
                        status_code=409,
                        detail=f"lab run {active_run_id} is already active",
                    )
                LAB_ACTIVE_RUN_ID = None
            _lab_router(session, payload.router_ip)
            _stockbot(session)
            _upsert_lab_plan(session, payload)
            run = create_run(session, "r1-ltap-live", "lab-current")
            cancel_event = Event()
            LAB_ACTIVE_RUN_ID = run.run_id
            LAB_CANCEL_EVENTS[run.run_id] = cancel_event
    except HTTPException:
        raise
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
    telemetry = []
    try:
        telemetry = adapter_for(run.router).collect_path_telemetry()
    except Exception:
        telemetry = []
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
        "active": run.state
        not in {
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.INTERRUPTED,
        },
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
            "live_metrics": _live_lab_metrics(session, run),
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
