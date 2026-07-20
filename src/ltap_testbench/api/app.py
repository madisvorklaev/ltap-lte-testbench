from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench import __version__
from ltap_testbench.db.base import get_session, init_db
from ltap_testbench.db.models import RouterProfile, ServerProfile, TestPlan, TestRun
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


app = FastAPI(title="LtAP LTE Testbench", version=__version__)


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
