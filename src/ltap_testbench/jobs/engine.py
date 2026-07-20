import json
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import (
    RouterProfile,
    RunEvent,
    RunState,
    ServerProfile,
    TestPlan,
    TestRun,
)
from ltap_testbench.jobs.state_machine import (
    TERMINAL_STATES,
    require_transition,
    restart_target_for,
)
from ltap_testbench.reporting.artifacts import persist_run_artifacts, run_artifact_dir
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight
from ltap_testbench.testnode.client import TestNodeClient, TestNodeReservation
from ltap_testbench.traffic.commands import run_command
from ltap_testbench.traffic.http_upload import parse_curl_write_out


def add_event(
    session: Session,
    run: TestRun,
    event_type: str,
    message: str,
    details: dict | None = None,
) -> None:
    run.events.append(RunEvent(event_type=event_type, message=message, details=details or {}))
    run.updated_at = utc_now()
    session.add(run)
    session.commit()


def transition(session: Session, run: TestRun, state: RunState, reason: str | None = None) -> None:
    require_transition(run.state, state)
    run.state = state
    run.state_reason = reason
    run.updated_at = utc_now()
    session.add(run)
    session.commit()
    add_event(session, run, "state", f"State changed to {state}", {"reason": reason})


def create_run(session: Session, router_slug: str, plan_slug: str) -> TestRun:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        raise ValueError(f"Unknown router profile: {router_slug}")
    plan = session.scalar(select(TestPlan).where(TestPlan.slug == plan_slug))
    if plan is None:
        raise ValueError(f"Unknown test plan: {plan_slug}")
    run = TestRun(
        run_id=f"run-{uuid4().hex[:12]}",
        router_id=router.id,
        plan_slug=plan.slug,
        resolved_plan=plan.definition,
    )
    session.add(run)
    session.commit()
    add_event(session, run, "created", "Run created.", {"router": router.slug, "plan": plan.slug})
    return run


def _server_for_run(session: Session, run: TestRun) -> ServerProfile | None:
    server_slug = run.resolved_plan.get("server_slug")
    if not server_slug:
        return None
    server = session.scalar(select(ServerProfile).where(ServerProfile.slug == server_slug))
    if server is None:
        raise ValueError(f"Unknown server profile: {server_slug}")
    return server


def _reserve_server(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
    client_factory: type[TestNodeClient],
) -> tuple[TestNodeReservation | None, TestNodeClient | None]:
    if server is None:
        add_event(session, run, "server-reservation", "No test node configured for this run.")
        return None, None
    client = client_factory(server.control_api_url)
    reservation = client.create_reservation("ltap-testbench", run_id=run.run_id)
    add_event(
        session,
        run,
        "server-reservation",
        f"Reserved test node {server.slug}.",
        {"server": server.slug, "reservation_id": reservation.id},
    )
    return reservation, client


def _release_server(
    session: Session,
    run: TestRun,
    reservation: TestNodeReservation | None,
    client: TestNodeClient | None,
) -> None:
    if reservation is None or client is None:
        return
    client.release_reservation(reservation.id)
    add_event(
        session,
        run,
        "server-release",
        "Released test node reservation.",
        {"reservation_id": reservation.id},
    )


def _plan_has_upload_stage(run: TestRun) -> bool:
    stages = run.resolved_plan.get("stages", [])
    return any("upload" in str(stage) for stage in stages)


def _router_paths(run: TestRun) -> list[dict]:
    paths = run.router.metadata_json.get("paths", [])
    return paths if isinstance(paths, list) else []


def _path_port(path: dict) -> int | None:
    ports = path.get("ports")
    if not isinstance(ports, dict):
        return None
    start = ports.get("start")
    return int(start) if start else None


def _execute_http_upload_stage(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
    client: TestNodeClient | None,
) -> list[dict]:
    if server is None or client is None or not _plan_has_upload_stage(run):
        add_event(session, run, "upload-stage", "No live HTTP upload stage configured.")
        return []
    if not server.public_host:
        raise RuntimeError(f"Server {server.slug} has no public_host for upload tests")

    artifact_dir = run_artifact_dir(run)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload_path = artifact_dir / "upload-payload.bin"
    payload_path.write_bytes((f"{run.run_id}\n".encode()) * 4096)

    results = []
    for path in _router_paths(run):
        path_id = path.get("id", "path")
        port = _path_port(path)
        if port is None:
            add_event(
                session,
                run,
                "upload-stage",
                f"Skipping {path_id}: no TCP port configured.",
                {"path": path},
            )
            continue
        upload_run_id = f"{run.run_id}-{path_id}"
        response_path = artifact_dir / f"{upload_run_id}_response.txt"
        url = f"http://{server.public_host}:{port}/upload/{upload_run_id}"
        write_out = json.dumps(
            {
                "http_code": "%{http_code}",
                "time_total": "%{time_total}",
                "speed_upload": "%{speed_upload}",
                "size_upload": "%{size_upload}",
                "remote_ip": "%{remote_ip}",
                "remote_port": "%{remote_port}",
            }
        )
        result = run_command(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail-with-body",
                "--upload-file",
                str(payload_path),
                "--output",
                str(response_path),
                "--write-out",
                write_out,
                url,
            ],
            timeout_seconds=60,
        )
        summary = parse_curl_write_out(result.stdout)
        connections = client.run_connections(upload_run_id)
        row = {
            "path_id": path_id,
            "url": url,
            "curl_exit_code": result.exit_code,
            "curl_stderr": result.stderr,
            "http_code": summary.http_code,
            "time_total_seconds": summary.time_total_seconds,
            "speed_upload_mbit_s": summary.speed_upload_mbit_s,
            "size_upload_bytes": summary.size_upload_bytes,
            "remote_ip": summary.remote_ip,
            "remote_port": summary.remote_port,
            "test_node_run_id": upload_run_id,
            "test_node_connections": connections,
        }
        add_event(session, run, "upload-stage", f"HTTP upload completed for {path_id}.", row)
        if result.exit_code != 0 or summary.http_code not in {"200", "201"} or not connections:
            raise RuntimeError(f"HTTP upload failed for {path_id}: {row}")
        results.append(row)
    return results


def execute_run(
    session: Session,
    run: TestRun,
    client_factory: type[TestNodeClient] = TestNodeClient,
) -> TestRun:
    router = run.router
    adapter = adapter_for(router)
    reservation: TestNodeReservation | None = None
    reservation_client: TestNodeClient | None = None
    try:
        transition(session, run, RunState.PREFLIGHT)
        server = _server_for_run(session, run)
        controller_check = common_preflight(router.controller_interface)
        add_event(
            session,
            run,
            "controller-preflight",
            "Controller preflight collected.",
            controller_check.to_dict(),
        )

        router_checks = adapter.preflight()
        for check in router_checks:
            add_event(session, run, "router-preflight", check.message, asdict(check))
        if any(not check.ok for check in router_checks):
            transition(session, run, RunState.FAILED, "router preflight failed")
            return run

        transition(session, run, RunState.VERIFYING_PATHS)
        path_checks = adapter.verify_paths()
        for check in path_checks:
            add_event(session, run, "path-verification", check.message, asdict(check))
        if any(not check.ok for check in path_checks):
            transition(session, run, RunState.FAILED, "path verification failed")
            return run

        transition(session, run, RunState.WARMING_UP)
        reservation, reservation_client = _reserve_server(session, run, server, client_factory)
        transition(session, run, RunState.RUNNING)
        upload_results = _execute_http_upload_stage(session, run, server, reservation_client)
        if not upload_results:
            add_event(
                session,
                run,
                "simulated-measurement",
                "MVP simulated measurement completed; no live upload stage ran.",
                {"latency_ms_median": 42.0, "latency_ms_p95": 88.0, "loss_percent": 0.0},
            )
        transition(session, run, RunState.COOLING_DOWN)
        transition(session, run, RunState.ANALYZING)
        connections = [
            connection
            for result in upload_results
            for connection in result.get("test_node_connections", [])
        ]
        run.summary = {
            "validity": "live-upload" if upload_results else "simulated",
            "warnings": controller_check.warnings,
            "message": (
                "Run completed with live HTTP upload stage."
                if upload_results
                else "MVP run completed using adapter checks and simulated measurements."
            ),
            "test_node_reserved": reservation is not None,
            "upload_results": upload_results,
            "test_node_connections": connections,
        }
        session.add(run)
        session.commit()
        transition(session, run, RunState.GENERATING_REPORT)
        transition(session, run, RunState.COMPLETED)
    except Exception as exc:
        add_event(session, run, "error", str(exc), {"type": type(exc).__name__})
        transition(session, run, RunState.FAILED, str(exc))
    finally:
        _release_server(session, run, reservation, reservation_client)
    persist_run_artifacts(run)
    return run


def request_cancel(session: Session, run: TestRun) -> TestRun:
    if run.state in TERMINAL_STATES:
        add_event(session, run, "cancel-ignored", "Run is already terminal.", {"state": run.state})
        return run
    if run.state == RunState.CREATED:
        transition(session, run, RunState.CANCELLED, "cancelled before start")
        return run
    transition(session, run, RunState.CANCEL_REQUESTED, "cancel requested")
    transition(session, run, RunState.RESTORING, "cleanup after cancellation")
    transition(session, run, RunState.CANCELLED, "cancelled cleanly")
    return run


def recover_incomplete_runs(session: Session) -> list[TestRun]:
    runs = session.scalars(select(TestRun).order_by(TestRun.id)).all()
    recovered: list[TestRun] = []
    for run in runs:
        target = restart_target_for(run.state)
        if target is None:
            continue
        transition(session, run, target, "worker restart recovery")
        if target == RunState.RESTORING:
            transition(
                session,
                run,
                RunState.RECOVERY_REQUIRED,
                "manual recovery required after restart",
            )
        recovered.append(run)
    return recovered
