from pathlib import Path
from threading import Lock, Thread

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
    udp_duration_seconds: int = 60
    udp_bitrate_mbit_s: float = 5.0
    antenna: str = ""


LAB_LOCK = Lock()
LAB_ACTIVE_RUN_ID: str | None = None
TCP_FILE_SIZE_OPTIONS_MB = [5, 10, 25, 50, 100]


app = FastAPI(title="LtAP LTE Testbench", version=__version__)


def _antenna_options(session: Session) -> list[str]:
    runs = session.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(100)).all()
    seen = []
    for run in runs:
        value = run.resolved_plan.get("lab", {}).get("antenna") if run.resolved_plan else None
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
        "stages": ["preflight", "path-verification", "idle-latency", "short-upload", "udp-upload"],
        "latency": {"duration_seconds": 10, "interval_ms": 1000},
        "tcp_upload": {
            "duration_seconds": 120,
            "parallel_streams": [1],
            "payload_bytes": tcp_bytes,
        },
        "udp_upload": {
            "duration_seconds": payload.udp_duration_seconds,
            "bitrate_mbit_s": payload.udp_bitrate_mbit_s,
            "datagram_bytes": 1200,
        },
        "traffic": {"path_concurrency": "parallel"},
        "telemetry": {"controller_interval_seconds": 1, "lte_interval_seconds": 5},
        "temporary_router_changes": {"disable_fasttrack": False, "clear_test_connections": True},
        "lab": {
            "router_ip": payload.router_ip,
            "tcp_file_size_mb": payload.tcp_file_size_mb,
            "udp_duration_seconds": payload.udp_duration_seconds,
            "udp_bitrate_mbit_s": payload.udp_bitrate_mbit_s,
            "antenna": payload.antenna,
        },
    }
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


def _run_lab_background(run_id: str) -> None:
    global LAB_ACTIVE_RUN_ID
    with SessionLocal() as session:
        run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
        if run is None:
            return
        execute_run(session, run)
    with LAB_LOCK:
        if run_id == LAB_ACTIVE_RUN_ID:
            LAB_ACTIVE_RUN_ID = None


def _latest_lab_run(session: Session) -> TestRun | None:
    if LAB_ACTIVE_RUN_ID:
        run = session.scalar(select(TestRun).where(TestRun.run_id == LAB_ACTIVE_RUN_ID))
        if run is not None:
            return run
    return session.scalar(select(TestRun).order_by(TestRun.id.desc()))


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
    if payload.udp_duration_seconds < 1 or payload.udp_duration_seconds > 3600:
        raise HTTPException(status_code=400, detail="UDP duration must be 1..3600 seconds")
    if payload.udp_bitrate_mbit_s <= 0 or payload.udp_bitrate_mbit_s > 50:
        raise HTTPException(status_code=400, detail="UDP bitrate must be 0..50 Mbit/s")
    try:
        _clear_lab_reservations(session)
        _lab_router(session, payload.router_ip)
        _stockbot(session)
        _upsert_lab_plan(session, payload)
        run = create_run(session, "r1-ltap-live", "lab-current")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with LAB_LOCK:
        LAB_ACTIVE_RUN_ID = run.run_id
    Thread(target=_run_lab_background, args=(run.run_id,), daemon=True).start()
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
            "description": run.resolved_plan.get("lab", {}),
            "summary": run.summary,
            "events": events,
            "telemetry": telemetry,
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
