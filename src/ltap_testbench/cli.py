import json
from pathlib import Path

import typer
import uvicorn
from sqlalchemy import select

from ltap_testbench.api.app import app as fastapi_app
from ltap_testbench.core.config import get_settings
from ltap_testbench.db.base import SessionLocal, init_db
from ltap_testbench.db.models import RouterProfile, ServerProfile, TestPlan, TestRun
from ltap_testbench.jobs.engine import create_run, execute_run, request_cancel
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.profiles.schemas import RouterProfileConfig, ServerProfileConfig, TestPlanConfig
from ltap_testbench.profiles.service import (
    create_router_profile,
    create_server_profile,
    create_test_plan,
)
from ltap_testbench.reporting.artifacts import list_run_artifacts
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight
from ltap_testbench.testnode.client import TestNodeClient

app = typer.Typer()
db_app = typer.Typer()
routers_app = typer.Typer()
runs_app = typer.Typer()
demo_app = typer.Typer()
servers_app = typer.Typer()
plans_app = typer.Typer()
app.add_typer(db_app, name="db")
app.add_typer(routers_app, name="routers")
app.add_typer(runs_app, name="runs")
app.add_typer(demo_app, name="demo")
app.add_typer(servers_app, name="servers")
app.add_typer(plans_app, name="plans")


def emit(data: object, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(data)


def read_json_file(path: Path) -> dict:
    return json.loads(path.read_text())


@db_app.command("init")
def db_init() -> None:
    init_db()
    typer.echo("database initialized")


@demo_app.command("seed")
def demo_seed() -> None:
    init_db()
    with SessionLocal() as session:
        seed_demo_data(session)
    typer.echo("demo profiles seeded")


@routers_app.command("list")
def routers_list(json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        routers = session.scalars(select(RouterProfile).order_by(RouterProfile.slug)).all()
        data = [
            {"slug": router.slug, "name": router.display_name, "kind": router.kind.value}
            for router in routers
        ]
    emit(data, json_output)


@routers_app.command("create")
def routers_create(
    json_file: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    config = RouterProfileConfig.model_validate(read_json_file(json_file))
    with SessionLocal() as session:
        router = create_router_profile(session, config)
        data = {
            "slug": router.slug,
            "name": router.display_name,
            "kind": router.kind.value,
        }
    emit(data, json_output)


@app.command("preflight")
def preflight(router_slug: str, json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
        if router is None:
            raise typer.BadParameter(f"unknown router: {router_slug}")
        controller = common_preflight(router.controller_interface)
        checks = adapter_for(router).preflight()
        data = {
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
    emit(data, json_output)


@app.command("run")
def run(
    router_slug: str,
    plan: str = "quick-check",
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    with SessionLocal() as session:
        test_run = create_run(session, router_slug, plan)
        test_run = execute_run(session, test_run)
        data = {
            "run_id": test_run.run_id,
            "state": test_run.state.value,
            "summary": test_run.summary,
        }
    emit(data, json_output)


@runs_app.command("list")
def runs_list(json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        runs = session.scalars(select(TestRun).order_by(TestRun.id.desc())).all()
        data = [
            {
                "run_id": run.run_id,
                "router": run.router.slug,
                "plan": run.plan_slug,
                "state": run.state.value,
            }
            for run in runs
        ]
    emit(data, json_output)


@runs_app.command("cancel")
def runs_cancel(run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        test_run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
        if test_run is None:
            raise typer.BadParameter(f"unknown run: {run_id}")
        test_run = request_cancel(session, test_run)
        data = {
            "run_id": test_run.run_id,
            "state": test_run.state.value,
            "reason": test_run.state_reason,
        }
    emit(data, json_output)


@runs_app.command("artifacts")
def runs_artifacts(run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        test_run = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
        if test_run is None:
            raise typer.BadParameter(f"unknown run: {run_id}")
        data = list_run_artifacts(test_run)
    emit(data, json_output)


@servers_app.command("list")
def servers_list(json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        servers = session.scalars(select(ServerProfile).order_by(ServerProfile.slug)).all()
        data = [
            {
                "slug": server.slug,
                "name": server.display_name,
                "control_api_url": server.control_api_url,
            }
            for server in servers
        ]
    emit(data, json_output)


@servers_app.command("create")
def servers_create(
    json_file: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    config = ServerProfileConfig.model_validate(read_json_file(json_file))
    with SessionLocal() as session:
        server = create_server_profile(session, config)
        data = {
            "slug": server.slug,
            "name": server.display_name,
            "control_api_url": server.control_api_url,
        }
    emit(data, json_output)


@servers_app.command("health")
def servers_health(server_slug: str, json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        server = session.scalar(select(ServerProfile).where(ServerProfile.slug == server_slug))
        if server is None:
            raise typer.BadParameter(f"unknown server: {server_slug}")
        data = TestNodeClient(server.control_api_url).health()
    emit(data, json_output)


@plans_app.command("create")
def plans_create(
    json_file: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    config = TestPlanConfig.model_validate(read_json_file(json_file))
    with SessionLocal() as session:
        plan = create_test_plan(session, config)
        data = {"slug": plan.slug, "name": plan.name, "version": plan.version}
    emit(data, json_output)


@plans_app.command("list")
def plans_list(json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        plans = session.scalars(select(TestPlan).order_by(TestPlan.slug)).all()
        data = [
            {
                "slug": plan.slug,
                "name": plan.name,
                "version": plan.version,
            }
            for plan in plans
        ]
    emit(data, json_output)


@app.command("serve")
def serve(
    host: str = typer.Option(None),
    port: int = typer.Option(None),
) -> None:
    settings = get_settings()
    uvicorn.run(fastapi_app, host=host or settings.bind_host, port=port or settings.bind_port)
