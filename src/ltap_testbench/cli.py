import json
from hashlib import sha256
from pathlib import Path

import typer
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench import __version__
from ltap_testbench.api.app import app as fastapi_app
from ltap_testbench.benchmarks.defaults import seed_benchmark_protocols
from ltap_testbench.core.config import get_settings
from ltap_testbench.core.time import utc_now
from ltap_testbench.db.base import SessionLocal, init_db
from ltap_testbench.db.models import (
    AntennaProfile,
    BatchState,
    BenchmarkProtocol,
    ComparisonDimension,
    Experiment,
    ExperimentVariant,
    GainSource,
    RouterKind,
    RouterProfile,
    ServerProfile,
    TestBatch,
    TestPlan,
    TestRun,
    TestSite,
)
from ltap_testbench.importers.legacy_csv import import_legacy_upload_csv
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


def _stable_hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sample_configuration(session: Session) -> dict:
    seed_benchmark_protocols(session)
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.slug == "comparable-v1")
    )
    if protocol is None:
        raise RuntimeError("comparable-v1 protocol was not seeded")
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == "r1-ltap-live"))
    if router is None:
        router = RouterProfile(
            slug="r1-ltap-live",
            display_name="R1 LtAP live",
            kind=RouterKind.MIKROTIK,
            management_host="192.168.101.254",
            management_protocol="routeros-api",
            username="admin",
            secret_ref="env:LTAP_R1_PASSWORD",
            expected_gateway="192.168.101.254",
            controller_interface="eno1",
            allow_configuration_changes=False,
            metadata_json={
                "paths": [
                    {"id": "lte1", "interface": "lte1", "udp_port": 18080},
                    {"id": "lte2", "interface": "lte2", "udp_port": 18081},
                ]
            },
        )
        session.add(router)
    antenna = session.scalar(
        select(AntennaProfile).where(AntennaProfile.slug == "generic-2dbi-window")
    )
    if antenna is None:
        antenna = AntennaProfile(
            slug="generic-2dbi-window",
            manufacturer="Generic",
            model="2 dBi window antenna",
            antenna_type="mimo",
            mimo_port_count=2,
            gain_source=GainSource.ESTIMATED,
            nominal_peak_gain_dbi=2.0,
            gain_by_band_json=[],
            cable_type="unknown",
            cable_length_m=2.0,
            estimated_cable_loss_db=None,
            connector_loss_db=None,
            mounting_location="window",
            orientation="current placement",
            notes=(
                "Sample profile. Installed effective gain is unknown because cable and "
                "connector losses are unknown."
            ),
        )
        session.add(antenna)
    site = session.scalar(select(TestSite).where(TestSite.slug == "current-location"))
    if site is None:
        site = TestSite(
            slug="current-location",
            name="Current location",
            location_description="Current connected-router test location",
            indoor_outdoor="indoor",
            notes="Created by sample configuration command.",
        )
        session.add(site)
    session.flush()
    experiment = session.scalar(
        select(Experiment).where(Experiment.name == "Connected router repeatability sample")
    )
    if experiment is None:
        experiment = Experiment(
            name="Connected router repeatability sample",
            comparison_dimension=ComparisonDimension.GENERAL_REPEATABILITY,
            protocol_id=protocol.id,
            site_id=site.id,
            hypothesis="Verify the connected LtAP setup can collect repeatable comparable-v1 runs.",
            primary_metrics_json=["tcp_mbit_s", "udp_loss_percent", "both_path_loss_percent"],
            practical_thresholds_json={},
        )
        session.add(experiment)
        session.flush()
    variant_snapshot = {
        "router_slug": router.slug,
        "antenna_profile_slug": antenna.slug,
        "site_slug": site.slug,
        "protocol_hash": protocol.protocol_hash,
        "antenna_mapping": {
            "lte1": {"antenna_profile_id": antenna.id, "ports": ["main", "aux"]},
            "lte2": {"antenna_profile_id": antenna.id, "ports": ["main", "aux"]},
        },
    }
    variant = session.scalar(
        select(ExperimentVariant).where(
            ExperimentVariant.experiment_id == experiment.id,
            ExperimentVariant.label == "current connected configuration",
        )
    )
    if variant is None:
        variant = ExperimentVariant(
            experiment_id=experiment.id,
            label="current connected configuration",
            antenna_mapping_json=variant_snapshot["antenna_mapping"],
            configuration_json=variant_snapshot,
        )
        session.add(variant)
        session.flush()
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == "sample-3-valid-5"))
    if batch is None:
        batch = TestBatch(
            batch_id="sample-3-valid-5",
            name="Sample 3 valid / 5 attempts",
            protocol_id=protocol.id,
            protocol_slug=protocol.slug,
            protocol_hash=protocol.protocol_hash,
            router_slug=router.slug,
            experiment_id=experiment.id,
            variant_id=variant.id,
            site_id=site.id,
            antenna_profile_id=antenna.id,
            state=BatchState.DRAFT,
            target_valid_runs=3,
            max_attempts=5,
            inter_run_cooldown_seconds=120,
            retry_delay_seconds=300,
            max_consecutive_failures=3,
            expected_application_version=__version__,
            expected_protocol_hash=protocol.protocol_hash,
            expected_variant_snapshot_hash=_stable_hash(variant_snapshot),
            notes="Draft sample batch. Validate readiness only; do not start automatically.",
            created_at=utc_now(),
        )
        session.add(batch)
    session.commit()
    readiness = {
        "router_profile": True,
        "antenna_profile": True,
        "site": True,
        "experiment": True,
        "variant": True,
        "draft_batch": batch.state == BatchState.DRAFT,
        "will_start": False,
    }
    return {
        "ok": all(value for key, value in readiness.items() if key != "will_start"),
        "readiness": readiness,
        "router": router.slug,
        "antenna_profile": antenna.slug,
        "effective_gain_dbi": None,
        "effective_gain_unknown_reason": "cable_and_or_connector_loss_unknown",
        "site": site.slug,
        "experiment_id": experiment.id,
        "variant_id": variant.id,
        "batch_id": batch.batch_id,
        "batch_state": batch.state.value,
        "target_valid_runs": batch.target_valid_runs,
        "max_attempts": batch.max_attempts,
        "protocol_hash": protocol.protocol_hash,
    }


@db_app.command("init")
def db_init() -> None:
    init_db()
    typer.echo("database initialized")


@app.command("create-sample-configuration")
def create_sample_configuration(json_output: bool = typer.Option(False, "--json")) -> None:
    init_db()
    with SessionLocal() as session:
        data = _sample_configuration(session)
    if json_output:
        emit(data, True)
        return
    typer.echo("Sample connected-router configuration is ready.")
    typer.echo(f"Router: {data['router']}")
    typer.echo(
        "Antenna: "
        f"{data['antenna_profile']} "
        f"(effective gain unknown: {data['effective_gain_unknown_reason']})"
    )
    typer.echo(f"Site: {data['site']}")
    typer.echo(f"Experiment ID: {data['experiment_id']}")
    typer.echo(f"Variant ID: {data['variant_id']}")
    typer.echo(
        f"Draft batch: {data['batch_id']} "
        f"({data['target_valid_runs']} valid / {data['max_attempts']} attempts)"
    )
    typer.echo("Readiness validated; batch was not started.")


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


@runs_app.command("import-legacy-csv")
def runs_import_legacy_csv(
    csv_file: Path = typer.Argument(..., exists=True, readable=True),
    router_slug: str = typer.Option(..., "--router"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    with SessionLocal() as session:
        imported = import_legacy_upload_csv(
            session,
            csv_path=csv_file,
            router_slug=router_slug,
        )
        data = [
            {
                "run_id": run.run_id,
                "state": run.state.value,
                "comparison_eligible": run.comparison_eligible,
                "exclusion_reasons": run.exclusion_reasons_json,
            }
            for run in imported
        ]
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


if __name__ == "__main__":
    app()
