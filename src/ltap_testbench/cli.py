import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

import typer
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench import __version__
from ltap_testbench.api.app import app as fastapi_app
from ltap_testbench.benchmarks.defaults import protocol_duration_seconds, seed_benchmark_protocols
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


def _sample_antenna_fields(slug: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "manufacturer": "Generic",
        "model": "Generic 2 dBi window antenna",
        "antenna_type": "window-mounted cellular antenna",
        "mimo_port_count": 2,
        "gain_source": GainSource.ESTIMATED,
        "nominal_peak_gain_dbi": 2.0,
        "gain_by_band_json": [],
        "cable_type": "unknown",
        "cable_length_m": 2.0,
        "estimated_cable_loss_db": None,
        "connector_loss_db": None,
        "mounting_location": "vehicle window",
        "orientation": "as installed; exact orientation unknown",
        "notes": (
            "Generic nominal 2 dBi window-mounted antenna. Cable type and cable/connector "
            "loss are unknown. The 2 dBi value is treated as estimated nominal antenna "
            "gain, not effective installed system gain."
        ),
    }


def _antenna_matches(profile: AntennaProfile, fields: dict[str, Any]) -> bool:
    return all(getattr(profile, key) == value for key, value in fields.items() if key != "slug")


def _versioned_slug(session: Session, model: Any, base_slug: str) -> str:
    index = 2
    while session.scalar(select(model).where(model.slug == f"{base_slug}-v{index}")) is not None:
        index += 1
    return f"{base_slug}-v{index}"


def _create_or_reuse_sample_antenna(session: Session) -> AntennaProfile:
    base_slug = "generic-2db-window-2m"
    fields = _sample_antenna_fields(base_slug)
    existing = session.scalar(select(AntennaProfile).where(AntennaProfile.slug == base_slug))
    if existing is not None and _antenna_matches(existing, fields):
        return existing
    if existing is not None:
        fields = _sample_antenna_fields(_versioned_slug(session, AntennaProfile, base_slug))
    antenna = AntennaProfile(**fields)
    session.add(antenna)
    session.flush()
    return antenna


def _path_id(path: dict[str, Any]) -> str:
    return str(path.get("id") or path.get("interface") or "lte")


def _normalize_router_paths(router: RouterProfile, snapshot: dict[str, Any] | None) -> list[dict]:
    metadata_paths = router.metadata_json.get("paths", []) if router.metadata_json else []
    paths = [dict(path) for path in metadata_paths if isinstance(path, dict)]
    if not paths and snapshot:
        for row in snapshot.get("paths", []):
            interface = row.get("interface") or row.get("path_id")
            if interface:
                paths.append({"id": str(row.get("path_id") or interface), "interface": interface})
    if not paths:
        paths = [{"id": "lte1", "interface": "lte1"}, {"id": "lte2", "interface": "lte2"}]
    normalized = []
    for path in paths:
        ports = path.get("ports") if isinstance(path.get("ports"), dict) else {}
        normalized.append(
            {
                "id": _path_id(path),
                "interface": path.get("interface") or _path_id(path),
                "routing_table": path.get("routing_table"),
                "source_address": path.get("source_address"),
                "expected_public_ip": path.get("expected_public_ip"),
                "ports": ports
                or {
                    "start": path.get("udp_port") or path.get("port"),
                    "end": path.get("udp_port") or path.get("port"),
                },
                "slot": path.get("slot"),
            }
        )
    return normalized


def _safe_router_profile_metadata(
    router: RouterProfile,
    paths: list[dict],
    snapshot: dict[str, Any] | None,
) -> dict:
    metadata = dict(router.metadata_json or {})
    metadata["paths"] = paths
    if snapshot:
        router_snapshot = snapshot.get("router", {})
        metadata["last_read_only_discovery"] = {
            "identity": router_snapshot.get("identity", {}),
            "resource": router_snapshot.get("resource", {}),
            "routerboard": router_snapshot.get("routerboard", {}),
            "packages": router_snapshot.get("packages", []),
        }
    return metadata


def _stable_modem_snapshot(paths_snapshot: list[dict], normalized_paths: list[dict]) -> dict:
    by_path = {str(row.get("path_id")): row for row in paths_snapshot}
    stable_paths = []
    for path in normalized_paths:
        row = by_path.get(_path_id(path), {})
        lte = row.get("lte", {}) if isinstance(row.get("lte"), dict) else {}
        monitor = row.get("monitor", {}) if isinstance(row.get("monitor"), dict) else {}
        stable_paths.append(
            {
                "path_id": _path_id(path),
                "interface": path.get("interface"),
                "slot": path.get("slot"),
                "imei_hash": lte.get("imei_hash") or monitor.get("imei_hash"),
                "imsi_hash": lte.get("imsi_hash") or monitor.get("imsi_hash"),
                "iccid_hash": lte.get("iccid_hash") or monitor.get("iccid_hash"),
                "model": monitor.get("model") or lte.get("modem") or lte.get("model"),
                "revision": monitor.get("revision") or monitor.get("modem-revision"),
            }
        )
    return {"paths": stable_paths}


def _antenna_mapping(paths: list[dict], antenna: AntennaProfile) -> dict:
    return {
        _path_id(path): {
            "antenna_profile_slug": antenna.slug,
            "antenna_profile_id": antenna.id,
            "ports": ["main", "aux"],
            "mapping_confidence": "assumed",
        }
        for path in paths
    }


def _server_health(server: ServerProfile | None) -> tuple[dict, list[str]]:
    if server is None:
        return {}, ["test_node_unavailable"]
    if not server.control_api_url:
        return {}, ["test_node_unavailable"]
    try:
        health = TestNodeClient(server.control_api_url).health()
    except Exception:
        return {}, ["test_node_unavailable"]
    errors = []
    if not health.get("version"):
        errors.append("test_node_version_missing")
    return health, errors


def _validation_errors(
    *,
    router: RouterProfile,
    router_error: str | None,
    path_checks: list[dict],
    protocol: BenchmarkProtocol | None,
    server_errors: list[str],
    normalized_paths: list[dict],
    batch: TestBatch,
    antenna: AntennaProfile,
    variant: ExperimentVariant,
) -> list[str]:
    errors = []
    if not router.secret_ref:
        errors.append("missing_router_credential")
    if router_error:
        errors.append(router_error)
    for check in path_checks:
        if not check["ok"]:
            if "route" in check["message"].lower():
                errors.append("route_table_invalid")
            else:
                errors.append("lte_path_missing")
    for path in normalized_paths:
        ports_value = path.get("ports")
        ports = ports_value if isinstance(ports_value, dict) else {}
        if not ports.get("start"):
            errors.append("required_port_missing")
    errors.extend(server_errors)
    if protocol is None:
        errors.append("protocol_missing")
    elif protocol.status.value != "frozen":
        errors.append("protocol_not_frozen")
    if antenna is None:
        errors.append("antenna_profile_missing")
    if variant.experiment_id != batch.experiment_id:
        errors.append("variant_does_not_belong_to_experiment")
    if protocol and batch.protocol_hash != protocol.protocol_hash:
        errors.append("protocol_hash_mismatch")
    if batch.state != BatchState.DRAFT:
        errors.append("batch_not_draft")
    return sorted(set(errors))


def _find_or_create_variant(
    session: Session,
    experiment: Experiment,
    *,
    base_label: str,
    router_snapshot: dict,
    configuration: dict,
    antenna_mapping: dict,
    modem_snapshot_hash: str,
) -> ExperimentVariant:
    variants = session.scalars(
        select(ExperimentVariant).where(ExperimentVariant.experiment_id == experiment.id)
    ).all()
    for variant in variants:
        if (
            variant.label.startswith(base_label)
            and variant.expected_modem_snapshot_hash == modem_snapshot_hash
            and variant.configuration_json == configuration
        ):
            return variant
    existing_labels = {variant.label for variant in variants}
    label = base_label
    index = 2
    while label in existing_labels:
        label = f"{base_label} v{index}"
        index += 1
    routerboard = router_snapshot.get("routerboard", {})
    resource = router_snapshot.get("resource", {})
    variant = ExperimentVariant(
        experiment_id=experiment.id,
        label=label,
        expected_routeros_version=resource.get("version"),
        expected_routerboot_version=routerboard.get("current-firmware"),
        expected_modem_snapshot_hash=modem_snapshot_hash,
        antenna_mapping_json=antenna_mapping,
        configuration_json=configuration,
    )
    session.add(variant)
    session.flush()
    return variant


def _sample_configuration(
    session: Session,
    *,
    router_slug: str = "r1-ltap-live",
    protocol_slug: str = "comparable-v1",
    target_valid_runs: int = 3,
    max_attempts: int = 5,
) -> dict:
    seed_benchmark_protocols(session)
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.slug == protocol_slug)
    )
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        router = RouterProfile(
            slug=router_slug,
            display_name="R1 LtAP live" if router_slug == "r1-ltap-live" else router_slug,
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
        session.flush()

    snapshot: dict[str, Any] | None = None
    router_error: str | None = None
    path_checks = []
    try:
        adapter = adapter_for(router)
        snapshot = adapter.collect_environment_snapshot()
        path_checks = [
            {
                "name": check.name,
                "ok": check.ok,
                "message": check.message,
                "details": check.details,
            }
            for check in adapter.verify_paths()
        ]
    except Exception as exc:
        router_error = "router_unreachable" if router.secret_ref else "missing_router_credential"
        path_checks = [
            {
                "name": "router-discovery",
                "ok": False,
                "message": str(exc),
                "details": {"type": type(exc).__name__},
            }
        ]

    normalized_paths = _normalize_router_paths(router, snapshot)
    router.metadata_json = _safe_router_profile_metadata(router, normalized_paths, snapshot)
    antenna = _create_or_reuse_sample_antenna(session)
    site = session.scalar(
        select(TestSite).where(TestSite.slug == "connected-router-current-location")
    )
    if site is None:
        site = TestSite(
            slug="connected-router-current-location",
            name="Connected router current test location",
            location_description=(
                "Current physical location of the connected router when the sample "
                "configuration was created."
            ),
            indoor_outdoor="vehicle / window-mounted antenna",
            notes=("Sample site record. Update the description if the router or antenna is moved."),
        )
        session.add(site)
    session.flush()
    experiment = session.scalar(
        select(Experiment).where(Experiment.name == "Sample dual-LTE repeatability baseline")
    )
    if experiment is None:
        experiment = Experiment(
            name="Sample dual-LTE repeatability baseline",
            comparison_dimension=ComparisonDimension.GENERAL_REPEATABILITY,
            protocol_id=protocol.id if protocol else None,
            site_id=site.id,
            hypothesis=(
                "Repeated comparable-v1 tests with the current router, modem, firmware, SIM, "
                "routing and antenna setup will establish the normal performance distribution "
                "and reveal transient dual-path outages."
            ),
            primary_metrics_json=[
                "tcp_mbit_s",
                "udp_mbit_s",
                "udp_loss_percent",
                "latency_p95_ms",
                "video_effective_redundant_success_percent",
                "video_both_path_loss_percent",
                "video_longest_both_path_outage_seconds",
            ],
            practical_thresholds_json={
                "tcp_relative": 0.10,
                "latency_p95_relative": 0.15,
                "latency_p95_absolute_ms": 10,
                "udp_loss_absolute_percentage_points": 0.2,
                "video_loss_absolute_percentage_points": 0.2,
                "longest_both_path_outage_seconds": 1.0,
            },
            random_seed=1001,
        )
        session.add(experiment)
        session.flush()
    server = session.scalar(select(ServerProfile).where(ServerProfile.slug == "stockbot"))
    if server is None:
        fallback_url = os.environ.get("LTAP_STOCKBOT_URL") or "http://127.0.0.1:8788"
        server = ServerProfile(
            slug="stockbot",
            display_name="Stockbot test node",
            control_api_url=fallback_url,
            public_host=os.environ.get("LTAP_STOCKBOT_PUBLIC_HOST"),
            metadata_json={},
        )
        session.add(server)
        session.flush()
    health, server_errors = _server_health(server)
    server.metadata_json = {
        **(server.metadata_json or {}),
        "last_health": health,
    }

    paths_snapshot = snapshot.get("paths", []) if snapshot else []
    modem_snapshot = _stable_modem_snapshot(paths_snapshot, normalized_paths)
    modem_snapshot_hash = _stable_hash(modem_snapshot)
    mapping = _antenna_mapping(normalized_paths, antenna)
    router_snapshot = (snapshot or {}).get("router", {})
    resource = router_snapshot.get("resource", {})
    routerboard = router_snapshot.get("routerboard", {})
    path_ids = [_path_id(path) for path in normalized_paths]
    variant_snapshot = {
        "router_slug": router.slug,
        "router_identity": router_snapshot.get("identity", {}),
        "router_board": routerboard.get("model") or routerboard.get("board-name"),
        "routeros_version": resource.get("version"),
        "routerboot_current_firmware": routerboard.get("current-firmware"),
        "routerboot_upgrade_firmware": routerboard.get("upgrade-firmware"),
        "path_count": len(normalized_paths),
        "path_ids": path_ids,
        "modem_snapshot_hash": modem_snapshot_hash,
        "modem_snapshot": modem_snapshot,
        "routing_tables": {_path_id(path): path.get("routing_table") for path in normalized_paths},
        "source_addresses": {
            _path_id(path): path.get("source_address") for path in normalized_paths
        },
        "test_node_slug": server.slug,
        "antenna_profile_slug": antenna.slug,
        "site_slug": site.slug,
        "protocol_hash": protocol.protocol_hash if protocol else None,
        "antenna_mapping": mapping,
    }
    variant = _find_or_create_variant(
        session,
        experiment,
        base_label="Current connected-router baseline",
        router_snapshot=router_snapshot,
        configuration=variant_snapshot,
        antenna_mapping=mapping,
        modem_snapshot_hash=modem_snapshot_hash,
    )
    batch_id = f"sample-comparable-baseline-{router.slug}-{target_valid_runs}v-{max_attempts}a"
    batch = session.scalar(select(TestBatch).where(TestBatch.batch_id == batch_id))
    if batch is None:
        batch = TestBatch(
            batch_id=batch_id,
            name="Sample comparable baseline series",
            protocol_id=protocol.id if protocol else None,
            protocol_slug=protocol_slug,
            protocol_hash=protocol.protocol_hash if protocol else "",
            router_slug=router.slug,
            experiment_id=experiment.id,
            variant_id=variant.id,
            site_id=site.id,
            antenna_profile_id=antenna.id,
            state=BatchState.DRAFT,
            target_valid_runs=target_valid_runs,
            max_attempts=max_attempts,
            inter_run_cooldown_seconds=120,
            retry_delay_seconds=300,
            max_consecutive_failures=3,
            expected_application_version=__version__,
            expected_test_node_version=health.get("version"),
            expected_protocol_hash=protocol.protocol_hash if protocol else None,
            expected_variant_snapshot_hash=_stable_hash(variant_snapshot),
            notes=(
                "Initial sample comparable-v1 series. Created from connected-router discovery. "
                "Do not use for antenna gain conclusions until physical antenna-to-modem and "
                "MIMO-port mapping has been verified."
            ),
            created_at=utc_now(),
        )
        session.add(batch)
    else:
        batch.variant_id = variant.id
        batch.experiment_id = experiment.id
        batch.site_id = site.id
        batch.antenna_profile_id = antenna.id
        batch.expected_variant_snapshot_hash = _stable_hash(variant_snapshot)
        batch.expected_test_node_version = health.get("version")
    duration_seconds = protocol_duration_seconds(protocol.definition_json) if protocol else 0
    cycle_seconds = duration_seconds + batch.inter_run_cooldown_seconds
    warnings = [
        "antenna cable loss unknown",
        "antenna connector loss unknown",
        "effective installed antenna gain unknown",
        "physical antenna mapping assumed",
        "coordinates not recorded",
        "current band/cell may vary between runs",
        "three valid runs are insufficient for a firm comparison conclusion",
    ]
    blocking_errors = _validation_errors(
        router=router,
        router_error=router_error,
        path_checks=path_checks,
        protocol=protocol,
        server_errors=server_errors,
        normalized_paths=normalized_paths,
        batch=batch,
        antenna=antenna,
        variant=variant,
    )
    session.commit()
    return {
        "configuration_created": True,
        "ready_to_start": not blocking_errors,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "router": {
            "profile": router.slug,
            "identity": router_snapshot.get("identity", {}),
            "board": routerboard,
            "resource": resource,
        },
        "paths": normalized_paths,
        "path_validation": path_checks,
        "test_node": {
            "slug": server.slug,
            "control_api_url": server.control_api_url,
            "public_host": server.public_host,
            "health": health,
        },
        "antenna_profile": {
            "id": antenna.id,
            "slug": antenna.slug,
            "manufacturer": antenna.manufacturer,
            "model": antenna.model,
            "gain_source": antenna.gain_source.value,
            "nominal_peak_gain_dbi": antenna.nominal_peak_gain_dbi,
            "cable_type": antenna.cable_type,
            "cable_length_m": antenna.cable_length_m,
            "estimated_cable_loss_db": antenna.estimated_cable_loss_db,
            "connector_loss_db": antenna.connector_loss_db,
            "effective_gain_dbi": None,
            "effective_gain_unknown_reason": "cable_and_or_connector_loss_unknown",
            "mapping": mapping,
        },
        "effective_gain_dbi": None,
        "effective_gain_unknown_reason": "cable_and_or_connector_loss_unknown",
        "site": {
            "id": site.id,
            "slug": site.slug,
            "name": site.name,
            "coordinates_recorded": site.latitude is not None and site.longitude is not None,
        },
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "comparison_dimension": experiment.comparison_dimension.value,
            "protocol_slug": protocol_slug,
        },
        "variant": {
            "id": variant.id,
            "label": variant.label,
            "expected_modem_snapshot_hash": variant.expected_modem_snapshot_hash,
            "configuration_hash": _stable_hash(variant_snapshot),
        },
        "batch": {
            "id": batch.id,
            "batch_id": batch.batch_id,
            "name": batch.name,
            "state": batch.state.value,
            "target_valid_runs": batch.target_valid_runs,
            "max_attempts": batch.max_attempts,
            "protocol_slug": batch.protocol_slug,
            "protocol_hash": batch.protocol_hash,
        },
        "estimated_duration": {
            "attempt_seconds": duration_seconds,
            "cycle_seconds": cycle_seconds,
            "minimum_total_seconds": duration_seconds * target_valid_runs
            + batch.inter_run_cooldown_seconds * max(0, target_valid_runs - 1),
            "worst_case_total_seconds": duration_seconds * max_attempts
            + batch.inter_run_cooldown_seconds * max(0, max_attempts - 1),
        },
    }


@db_app.command("init")
def db_init() -> None:
    init_db()
    typer.echo("database initialized")


@app.command("create-sample-configuration")
def create_sample_configuration(
    router_slug: str = typer.Option("r1-ltap-live", "--router-slug"),
    protocol_slug: str = typer.Option("comparable-v1", "--protocol"),
    target_valid_runs: int = typer.Option(3, "--target-valid-runs"),
    max_attempts: int = typer.Option(5, "--max-attempts"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    init_db()
    with SessionLocal() as session:
        data = _sample_configuration(
            session,
            router_slug=router_slug,
            protocol_slug=protocol_slug,
            target_valid_runs=target_valid_runs,
            max_attempts=max_attempts,
        )
    if json_output:
        emit(data, True)
        if data["blocking_errors"]:
            raise typer.Exit(1)
        return
    router = data["router"]
    resource = router["resource"]
    routerboard = router["board"]
    antenna = data["antenna_profile"]
    batch = data["batch"]
    duration = data["estimated_duration"]

    typer.echo("Sample comparable LTE configuration created")
    typer.echo("")
    typer.echo("Router:")
    typer.echo(f" Profile: {router['profile']}")
    typer.echo(f" Identity: {router['identity'].get('name') or 'unknown'}")
    typer.echo(f" Board: {routerboard.get('model') or routerboard.get('board-name') or 'unknown'}")
    typer.echo(f" RouterOS: {resource.get('version') or 'unknown'}")
    typer.echo(f" RouterBOOT: {routerboard.get('current-firmware') or 'unknown'}")
    typer.echo("")
    typer.echo("LTE paths:")
    for path in data["paths"]:
        ports = path.get("ports") if isinstance(path.get("ports"), dict) else {}
        typer.echo(
            f" {_path_id(path)}: {path.get('interface')}, "
            f"routing table {path.get('routing_table') or 'unknown'}, "
            f"ports {ports.get('start') or 'unknown'}"
        )
    typer.echo("")
    typer.echo("Antenna:")
    typer.echo(f" {antenna['model']}")
    typer.echo(f" Nominal gain: {antenna['nominal_peak_gain_dbi']} dBi (estimated)")
    typer.echo(f" Cable: {antenna['cable_length_m']} m, type {antenna['cable_type']}")
    typer.echo(" Effective installed gain: unknown")
    typer.echo(" Mapping: assumed; physical verification required")
    typer.echo("")
    typer.echo("Experiment:")
    typer.echo(f" {data['experiment']['name']}")
    typer.echo("")
    typer.echo("Batch:")
    typer.echo(f" {batch['name']}")
    typer.echo(f" Target valid runs: {batch['target_valid_runs']}")
    typer.echo(f" Maximum attempts: {batch['max_attempts']}")
    typer.echo(f" Protocol: {batch['protocol_slug']}")
    typer.echo(f" State: {batch['state']}")
    typer.echo(
        " Estimated duration: "
        f"{duration['attempt_seconds']} s/attempt, "
        f"{duration['cycle_seconds']} s/cycle, "
        f"{duration['minimum_total_seconds']} s minimum, "
        f"{duration['worst_case_total_seconds']} s worst case"
    )
    typer.echo("")
    typer.echo(f"Ready to start: {'YES' if data['ready_to_start'] else 'NO'}")
    typer.echo("")
    typer.echo("Warnings:")
    for warning in data["warnings"]:
        typer.echo(f" - {warning}")
    typer.echo("Blocking errors:")
    if data["blocking_errors"]:
        for error in data["blocking_errors"]:
            typer.echo(f" - {error}")
        raise typer.Exit(1)
    typer.echo(" - none")


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
