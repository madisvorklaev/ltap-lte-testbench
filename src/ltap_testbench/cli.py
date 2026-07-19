import json

import typer
import uvicorn
from sqlalchemy import select

from ltap_testbench.api.app import app as fastapi_app
from ltap_testbench.core.config import get_settings
from ltap_testbench.db.base import SessionLocal, init_db
from ltap_testbench.db.models import RouterProfile, TestRun
from ltap_testbench.jobs.engine import create_run, execute_run, request_cancel
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight

app = typer.Typer()
db_app = typer.Typer()
routers_app = typer.Typer()
runs_app = typer.Typer()
demo_app = typer.Typer()
app.add_typer(db_app, name="db")
app.add_typer(routers_app, name="routers")
app.add_typer(runs_app, name="runs")
app.add_typer(demo_app, name="demo")


def emit(data: object, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(data)


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


@app.command("serve")
def serve(
    host: str = typer.Option(None),
    port: int = typer.Option(None),
) -> None:
    settings = get_settings()
    uvicorn.run(fastapi_app, host=host or settings.bind_host, port=port or settings.bind_port)
