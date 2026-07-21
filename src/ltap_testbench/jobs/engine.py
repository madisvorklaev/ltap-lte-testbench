import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from threading import Event
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ltap_testbench import __version__
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
from ltap_testbench.profiles.protocols import protocol_metadata
from ltap_testbench.profiles.schemas import STAGE_ALIASES
from ltap_testbench.reporting.artifacts import persist_run_artifacts, run_artifact_dir
from ltap_testbench.routers.base import RouterAdapter
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight
from ltap_testbench.telemetry.sampler import RunMetricSampler
from ltap_testbench.testnode.client import TestNodeClient, TestNodeReservation
from ltap_testbench.traffic.commands import run_command
from ltap_testbench.traffic.http_upload import parse_curl_write_out
from ltap_testbench.traffic.tcp_upload import run_timed_tcp_upload
from ltap_testbench.traffic.udp_upload import run_udp_upload
from ltap_testbench.traffic.video_udp import run_video_udp_probe

TCP_UPLOAD_STAGE = "tcp-upload"
UDP_UPLOAD_STAGE = "udp-upload"
VIDEO_PROBE_STAGE = "video-udp-probe"


class RunCancelledError(RuntimeError):
    pass


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


def _stable_hash(data: dict) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _application_git_commit() -> str | None:
    repo_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def create_run(session: Session, router_slug: str, plan_slug: str) -> TestRun:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        raise ValueError(f"Unknown router profile: {router_slug}")
    plan = session.scalar(select(TestPlan).where(TestPlan.slug == plan_slug))
    if plan is None:
        raise ValueError(f"Unknown test plan: {plan_slug}")
    resolved_plan = _normalize_plan_definition(plan.definition)
    protocol = resolved_plan.setdefault("metadata", {}).setdefault("protocol", {})
    existing_hash = protocol.get("protocol_hash") if isinstance(protocol, dict) else None
    protocol.update(protocol_metadata(resolved_plan))
    if existing_hash:
        protocol["protocol_hash"] = existing_hash
    run = TestRun(
        run_id=f"run-{uuid4().hex[:12]}",
        router_id=router.id,
        plan_slug=plan.slug,
        resolved_plan=resolved_plan,
        protocol_hash=protocol.get("protocol_hash"),
        result_schema_version=int(protocol.get("result_schema_version") or 1),
        application_version=__version__,
        application_git_commit=_application_git_commit(),
    )
    session.add(run)
    session.commit()
    add_event(session, run, "created", "Run created.", {"router": router.slug, "plan": plan.slug})
    return run


def _capture_environment_snapshot(
    session: Session,
    run: TestRun,
    adapter: RouterAdapter,
    server: ServerProfile | None,
    client_factory: type[TestNodeClient],
) -> None:
    snapshot: dict = {
        "schema_version": 1,
        "captured_at": utc_now().isoformat(),
        "application": {
            "version": __version__,
            "git_commit": run.application_git_commit or _application_git_commit(),
        },
        "test_node": {},
    }
    if server is not None:
        snapshot["test_node"] = {
            "slug": server.slug,
            "url": server.control_api_url,
        }
        try:
            health = client_factory(server.control_api_url).health()
            snapshot["test_node"]["health"] = health
            snapshot["test_node"]["version"] = health.get("version")
            run.test_node_version = str(health.get("version")) if health.get("version") else None
        except Exception as exc:
            snapshot["test_node"]["health_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
    try:
        snapshot.update(adapter.collect_environment_snapshot())
        snapshot_complete = True
    except Exception as exc:
        snapshot["router_snapshot_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        snapshot_complete = False
    run.environment_snapshot_json = snapshot
    run.environment_snapshot_hash = _stable_hash(snapshot)
    run.application_version = __version__
    run.application_git_commit = snapshot["application"]["git_commit"]
    run.integrity_json = {
        **(run.integrity_json or {}),
        "environment_snapshot_complete": snapshot_complete,
        "test_node_version_verified": bool(run.test_node_version),
    }
    session.add(run)
    session.commit()
    add_event(
        session,
        run,
        "environment-snapshot",
        "Environment snapshot captured.",
        {
            "snapshot_hash": run.environment_snapshot_hash,
            "complete": snapshot_complete,
            "test_node_version": run.test_node_version,
        },
    )


def _normalize_plan_definition(definition: dict) -> dict:
    normalized = {**definition}
    stages = normalized.get("stages", [])
    if isinstance(stages, list):
        normalized["stages"] = [
            STAGE_ALIASES[stage].value
            if isinstance(stage, str) and stage in STAGE_ALIASES
            else str(stage)
            for stage in stages
        ]
    return normalized


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
    return TCP_UPLOAD_STAGE in _plan_stage_set(run)


def _plan_has_udp_upload_stage(run: TestRun) -> bool:
    return UDP_UPLOAD_STAGE in _plan_stage_set(run)


def _plan_has_latency_stage(run: TestRun) -> bool:
    return "idle-latency" in _plan_stage_set(run)


def _plan_stage_set(run: TestRun) -> set[str]:
    stages = run.resolved_plan.get("stages", [])
    if not isinstance(stages, list):
        return set()
    return {
        STAGE_ALIASES[stage].value
        if isinstance(stage, str) and stage in STAGE_ALIASES
        else str(stage)
        for stage in stages
    }


def _router_paths(run: TestRun) -> list[dict]:
    paths = run.router.metadata_json.get("paths", [])
    return paths if isinstance(paths, list) else []


def _path_port(path: dict) -> int | None:
    ports = path.get("ports")
    if not isinstance(ports, dict):
        return None
    start = ports.get("start")
    return int(start) if start else None


def _tcp_upload_config(run: TestRun) -> dict:
    config = run.resolved_plan.get("tcp_upload", {})
    return config if isinstance(config, dict) else {}


def _udp_upload_config(run: TestRun) -> dict:
    config = run.resolved_plan.get("udp_upload", {})
    return config if isinstance(config, dict) else {}


def _latency_config(run: TestRun) -> dict:
    config = run.resolved_plan.get("latency", {})
    return config if isinstance(config, dict) else {}


def _video_probe_config(run: TestRun) -> dict:
    config = run.resolved_plan.get("video_probe", {})
    return config if isinstance(config, dict) else {}


def _plan_has_video_probe_stage(run: TestRun) -> bool:
    config = _video_probe_config(run)
    if config.get("enabled") is False:
        return False
    return VIDEO_PROBE_STAGE in _plan_stage_set(run)


def _tcp_upload_count(run: TestRun) -> int:
    config = _tcp_upload_config(run)
    return max(1, int(config.get("count", 1)))


def _udp_pattern(run: TestRun) -> str:
    config = _udp_upload_config(run)
    pattern = str(config.get("pattern", "end"))
    if pattern not in {"after_each_tcp", "beginning", "end"}:
        return "end"
    return pattern


def _safe_router_telemetry(
    session: Session,
    run: TestRun,
    adapter: RouterAdapter,
    label: str,
) -> list[dict]:
    try:
        rows = adapter.collect_path_telemetry()
    except Exception as exc:
        add_event(
            session,
            run,
            "router-telemetry",
            f"Router telemetry collection failed during {label}.",
            {"type": type(exc).__name__, "error": str(exc)},
        )
        return []
    add_event(
        session,
        run,
        "router-telemetry",
        f"Router telemetry collected during {label}.",
        {"label": label, "paths": rows},
    )
    return rows


def _metric_sampler_for_run(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
) -> RunMetricSampler | None:
    bind = session.get_bind()
    bind_url = getattr(bind, "url", None)
    database = getattr(bind_url, "database", None)
    if bind.dialect.name == "sqlite" and database in {
        None,
        "",
        ":memory:",
    }:
        return None
    latency = _latency_config(run)
    telemetry = run.resolved_plan.get("telemetry", {})
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    latency_interval_seconds = max(0.1, int(latency.get("interval_ms", 1000)) / 1000)
    radio_interval_seconds = float(
        telemetry.get("lte_interval_seconds")
        or telemetry.get("interval_seconds")
        or telemetry.get("radio_interval_seconds")
        or 5
    )
    factory = sessionmaker(bind=bind, expire_on_commit=False, future=True)
    return RunMetricSampler(
        factory,
        run.run_id,
        target_host=server.public_host if server is not None else None,
        latency_interval_seconds=latency_interval_seconds,
        radio_interval_seconds=radio_interval_seconds,
    )


def _is_cancel_requested(session: Session, run: TestRun, cancel_event: Event | None) -> bool:
    if cancel_event is not None and cancel_event.is_set():
        return True
    session.refresh(run)
    return run.state == RunState.CANCEL_REQUESTED


def _raise_if_cancelled(session: Session, run: TestRun, cancel_event: Event | None) -> None:
    if _is_cancel_requested(session, run, cancel_event):
        raise RunCancelledError("run cancellation requested")


def _transition_cancelled(session: Session, run: TestRun) -> None:
    session.refresh(run)
    if run.state != RunState.CANCEL_REQUESTED and run.state != RunState.RESTORING:
        transition(session, run, RunState.CANCEL_REQUESTED, "cancel requested")
    if run.state == RunState.CANCEL_REQUESTED:
        transition(session, run, RunState.RESTORING, "cleanup after cancellation")
    transition(session, run, RunState.CANCELLED, "cancelled cleanly")


def _execute_latency_stage(
    session: Session,
    run: TestRun,
    adapter: RouterAdapter,
    server: ServerProfile | None,
) -> list[dict]:
    if server is None or not server.public_host or not _plan_has_latency_stage(run):
        add_event(session, run, "latency-stage", "No live latency stage configured.")
        return []
    config = _latency_config(run)
    interval_ms = int(config.get("interval_ms", 100))
    duration_seconds = int(config.get("duration_seconds", 60))
    count = max(1, min(50, int(duration_seconds * 1000 / interval_ms)))
    results = adapter.measure_latency(server.public_host, count=count)
    add_event(
        session,
        run,
        "latency-stage",
        "Router-originated latency probes completed.",
        {"target_host": server.public_host, "count": count, "results": results},
    )
    return results


def _execute_http_upload_stage(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
    client: TestNodeClient | None,
    round_index: int = 1,
    total_rounds: int = 1,
    cancel_event: Event | None = None,
) -> list[dict]:
    if server is None or client is None or not _plan_has_upload_stage(run):
        add_event(session, run, "upload-stage", "No live HTTP upload stage configured.")
        return []
    if not server.public_host:
        raise RuntimeError(f"Server {server.slug} has no public_host for upload tests")
    public_host = server.public_host

    config = _tcp_upload_config(run)
    raw_payload_bytes = config.get("payload_bytes")
    payload_bytes = int(raw_payload_bytes) if raw_payload_bytes else None
    duration_seconds = int(config.get("duration_seconds", 30))
    artifact_dir = run_artifact_dir(run)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload_path = artifact_dir / "upload-payload.bin"
    if payload_bytes is not None:
        pattern = f"{run.run_id}\n".encode()
        repeats = payload_bytes // len(pattern) + 1
        payload_path.write_bytes((pattern * repeats)[:payload_bytes])

    paths = _router_paths(run)
    add_event(
        session,
        run,
        "upload-stage-started",
        "TCP upload stage started.",
        {
            "paths": [path.get("id", "path") for path in paths],
            "mode": "timed" if payload_bytes is None else "payload",
            "payload_bytes": payload_bytes,
            "duration_seconds": duration_seconds,
            "round": round_index,
            "rounds": total_rounds,
            "parallel_paths": True,
        },
    )

    def run_path(path: dict) -> dict:
        path_id = path.get("id", "path")
        port = _path_port(path)
        if port is None:
            return {"path_id": path_id, "skipped": True, "reason": "no TCP port configured"}
        upload_run_id = f"{run.run_id}-{path_id}-tcp{round_index}"
        response_path = artifact_dir / f"{upload_run_id}_response.txt"
        url = f"http://{public_host}:{port}/upload/{upload_run_id}"
        if payload_bytes is None:
            timed = run_timed_tcp_upload(
                public_host,
                port,
                f"/upload/{upload_run_id}",
                duration_seconds,
                should_cancel=cancel_event.is_set if cancel_event is not None else None,
            )
            result = None
            summary = None
            response_path.write_text(timed.response_head)
        else:
            write_out = json.dumps(
                {
                    "http_code": "%{http_code}",
                    "time_connect": "%{time_connect}",
                    "time_total": "%{time_total}",
                    "speed_upload": "%{speed_upload}",
                    "size_upload": "%{size_upload}",
                    "remote_ip": "%{remote_ip}",
                    "remote_port": "%{remote_port}",
                }
            )
            timeout_seconds = max(duration_seconds + 120, 120)
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
                timeout_seconds=timeout_seconds,
                should_cancel=cancel_event.is_set if cancel_event is not None else None,
            )
            summary = parse_curl_write_out(result.stdout) if result.stdout.strip() else None
            timed = None
        connections = client.run_connections(upload_run_id)
        server_bytes = sum(int(connection.get("bytes_received") or 0) for connection in connections)
        server_duration = max(
            [float(connection.get("duration_seconds") or 0) for connection in connections],
            default=None,
        )
        server_mbit_s = (
            max(float(connection.get("average_mbit_s") or 0) for connection in connections)
            if connections
            else None
        )
        time_total_seconds: float | None
        speed_upload_mbit_s: float | None
        size_upload_bytes: int | None
        if timed is not None:
            time_total_seconds = timed.duration_seconds
            speed_upload_mbit_s = timed.average_mbit_s
            size_upload_bytes = timed.bytes_sent
            http_code = None
        elif summary is not None:
            time_total_seconds = summary.time_total_seconds
            speed_upload_mbit_s = summary.speed_upload_mbit_s
            size_upload_bytes = summary.size_upload_bytes
            http_code = summary.http_code
        else:
            time_total_seconds = None
            speed_upload_mbit_s = None
            size_upload_bytes = None
            http_code = None
        row = {
            "path_id": path_id,
            "round": round_index,
            "rounds": total_rounds,
            "url": url,
            "target_host": public_host,
            "target_port": port,
            "mode": "timed" if payload_bytes is None else "payload",
            "curl_exit_code": result.exit_code if result is not None else None,
            "curl_stderr": result.stderr if result is not None else None,
            "http_code": http_code,
            "time_connect_seconds": summary.time_connect_seconds if summary is not None else None,
            "time_total_seconds": time_total_seconds,
            "speed_upload_mbit_s": speed_upload_mbit_s,
            "size_upload_bytes": size_upload_bytes,
            "configured_duration_seconds": duration_seconds,
            "configured_payload_bytes": payload_bytes,
            "remote_ip": summary.remote_ip if summary is not None else public_host,
            "remote_port": summary.remote_port if summary is not None else port,
            "response_artifact": response_path.name,
            "server_bytes_received": server_bytes,
            "server_duration_seconds": server_duration,
            "server_average_mbit_s": server_mbit_s,
            "test_node_run_id": upload_run_id,
            "test_node_connections": connections,
        }
        expected_server_bytes = payload_bytes if payload_bytes is not None else 1
        server_confirmed = bool(connections) and server_bytes >= expected_server_bytes
        curl_confirmed = (
            result is not None and result.exit_code == 0 and http_code in {"200", "201"}
        )
        timed_confirmed = timed is not None and timed.bytes_sent > 0
        if server_confirmed:
            row["validity"] = "server-confirmed"
        elif curl_confirmed or timed_confirmed:
            row["validity"] = "sender-only"
        else:
            row["validity"] = "failed"
        if (
            not server_confirmed
            and not curl_confirmed
            and not timed_confirmed
            and cancel_event is not None
            and cancel_event.is_set()
        ):
            row["validity"] = "cancelled"
            return row
        if not server_confirmed and not curl_confirmed and not timed_confirmed:
            raise RuntimeError(f"HTTP upload failed for {path_id}: {row}")
        return row

    results = []
    max_workers = max(1, len(paths))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_path, path): path for path in paths}
        for future in as_completed(futures):
            row = future.result()
            if row.get("skipped"):
                add_event(
                    session,
                    run,
                    "upload-stage",
                    f"Skipping {row['path_id']}: {row['reason']}.",
                    {"path": futures[future]},
                )
                continue
            add_event(
                session,
                run,
                "upload-stage",
                f"HTTP upload completed for {row['path_id']}.",
                row,
            )
            results.append(row)
    return results


def _execute_udp_upload_stage(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
    label: str = "end",
    cancel_event: Event | None = None,
) -> list[dict]:
    if server is None or not _plan_has_udp_upload_stage(run):
        add_event(session, run, "udp-upload-stage", "No UDP upload stage configured.")
        return []
    if not server.public_host:
        raise RuntimeError(f"Server {server.slug} has no public_host for UDP upload tests")
    public_host = server.public_host
    config = _udp_upload_config(run)
    duration_seconds = int(config.get("duration_seconds", 30))
    bitrate_mbit_s = float(config.get("bitrate_mbit_s", 2.0))
    datagram_bytes = int(config.get("datagram_bytes", 1200))
    paths = _router_paths(run)
    add_event(
        session,
        run,
        "udp-upload-stage-started",
        "UDP upload stage started.",
        {
            "paths": [path.get("id", "path") for path in paths],
            "duration_seconds": duration_seconds,
            "bitrate_mbit_s": bitrate_mbit_s,
            "datagram_bytes": datagram_bytes,
            "label": label,
            "parallel_paths": True,
        },
    )

    def run_path(path: dict) -> dict:
        path_id = path.get("id", "path")
        port = _path_port(path)
        if port is None:
            return {"path_id": path_id, "skipped": True, "reason": "no UDP port configured"}
        udp_run_id = f"{run.run_id}-{path_id}-udp-{label}"
        result = run_udp_upload(
            public_host,
            port,
            duration_seconds,
            bitrate_mbit_s,
            datagram_bytes,
            run_id=udp_run_id,
            should_cancel=cancel_event.is_set if cancel_event is not None else None,
        )
        connections = []
        if server.public_host and server:
            try:
                connections = TestNodeClient(server.control_api_url).run_connections(udp_run_id)
            except Exception:
                connections = []
        receiver = connections[0] if connections else {}
        receiver_bytes = int(receiver.get("bytes_received") or 0)
        receiver_unique = int(
            receiver.get("unique_datagrams") or receiver.get("datagrams_received") or 0
        )
        receiver_duration = float(receiver.get("duration_seconds") or 0.0)
        delivered_mbit_s = (
            float(receiver.get("delivered_mbit_s") or receiver.get("average_mbit_s") or 0.0)
            if receiver
            else None
        )
        packet_loss_percent = (
            max(0, result.datagrams_sent - receiver_unique) / result.datagrams_sent * 100
            if result.datagrams_sent
            else None
        )
        byte_delivery_percent = (
            receiver_bytes / result.bytes_sent * 100 if result.bytes_sent else None
        )
        row = {
            "path_id": path_id,
            "label": label,
            "test_node_run_id": udp_run_id,
            "target_host": result.target_host,
            "target_port": result.target_port,
            "requested_duration_seconds": result.requested_duration_seconds,
            "duration_seconds": result.duration_seconds,
            "configured_bitrate_mbit_s": result.bitrate_mbit_s,
            "average_mbit_s": result.average_mbit_s,
            "datagram_bytes": result.datagram_bytes,
            "datagrams_sent": result.datagrams_sent,
            "bytes_sent": result.bytes_sent,
            "sender": {
                "bytes": result.bytes_sent,
                "datagrams": result.datagrams_sent,
                "average_mbit_s": result.average_mbit_s,
            },
            "receiver": {
                "bytes": receiver_bytes,
                "unique_datagrams": receiver_unique,
                "datagrams_received": int(receiver.get("datagrams_received") or 0),
                "duplicates": int(receiver.get("duplicates") or 0),
                "out_of_order": int(receiver.get("out_of_order") or 0),
                "missing_datagrams": int(
                    receiver.get("missing_datagrams")
                    or max(0, result.datagrams_sent - receiver_unique)
                ),
                "duration_seconds": receiver_duration,
                "delivered_mbit_s": delivered_mbit_s,
            },
            "delivery": {
                "packet_loss_percent": packet_loss_percent,
                "byte_delivery_percent": byte_delivery_percent,
            },
            "server_average_mbit_s": delivered_mbit_s,
            "packet_loss_percent": packet_loss_percent,
            "byte_delivery_percent": byte_delivery_percent,
            "validity": "server-confirmed" if connections else "sender-side",
            "server_confirmation": bool(connections),
            "test_node_connections": connections,
        }
        return row

    rows = []
    max_workers = max(1, len(paths))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_path, path): path for path in paths}
        for future in as_completed(futures):
            row = future.result()
            if row.get("skipped"):
                add_event(
                    session,
                    run,
                    "udp-upload-stage",
                    f"Skipping {row['path_id']}: {row['reason']}.",
                    {"path": futures[future]},
                )
                continue
            add_event(
                session,
                run,
                "udp-upload-stage",
                f"UDP upload completed for {row['path_id']}.",
                row,
            )
            rows.append(row)
    return rows


def _execute_video_probe_stage(
    session: Session,
    run: TestRun,
    server: ServerProfile | None,
    cancel_event: Event | None = None,
) -> dict:
    if server is None or not _plan_has_video_probe_stage(run):
        add_event(session, run, "video-probe-stage", "No UDP video frame probe configured.")
        return {}
    if not server.public_host:
        raise RuntimeError(f"Server {server.slug} has no public_host for video probe")
    public_host = server.public_host
    config = _video_probe_config(run)
    duration_seconds = int(config.get("duration_seconds", 30))
    bitrate_mbit_s = float(config.get("bitrate_mbit_s", 5.0))
    fps = int(config.get("fps", 25))
    resolution = str(config.get("resolution", "1080p"))
    scenario = str(config.get("scenario", "city"))
    payload_bytes = int(config.get("payload_bytes", 1200))
    traffic_seed = str(config.get("traffic_seed", "video-trace-v1"))
    trace_id = str(config.get("trace_id", f"synthetic-{scenario}-v1"))
    generator_version = str(config.get("generator_version", "synthetic-video-v2"))
    receiver_settle_seconds = max(0, min(30, int(config.get("receiver_settle_seconds", 5))))
    paths = _router_paths(run)
    add_event(
        session,
        run,
        "video-probe-stage-started",
        "UDP video frame probe started.",
        {
            "paths": [path.get("id", "path") for path in paths],
            "duration_seconds": duration_seconds,
            "bitrate_mbit_s": bitrate_mbit_s,
            "fps": fps,
            "resolution": resolution,
            "scenario": scenario,
            "payload_bytes": payload_bytes,
            "traffic_seed": traffic_seed,
            "trace_id": trace_id,
            "generator_version": generator_version,
            "parallel_paths": True,
        },
    )

    def run_path(path: dict) -> dict:
        path_id = path.get("id", "path")
        port = _path_port(path)
        if port is None:
            return {"path_id": path_id, "skipped": True, "reason": "no UDP port configured"}
        probe_run_id = f"{run.run_id}-video"
        result = run_video_udp_probe(
            public_host,
            port,
            probe_run_id,
            path_id,
            duration_seconds,
            bitrate_mbit_s,
            fps=fps,
            resolution=resolution,
            scenario=scenario,
            payload_bytes=payload_bytes,
            traffic_seed=traffic_seed,
            trace_id=trace_id,
            generator_version=generator_version,
            should_cancel=cancel_event.is_set if cancel_event is not None else None,
        )
        return {
            "path_id": path_id,
            "test_node_run_id": probe_run_id,
            "target_host": result.target_host,
            "target_port": result.target_port,
            "resolution": result.resolution,
            "scenario": result.scenario,
            "duration_seconds": result.duration_seconds,
            "requested_duration_seconds": result.requested_duration_seconds,
            "bitrate_mbit_s": result.bitrate_mbit_s,
            "fps": result.fps,
            "payload_bytes": result.payload_bytes,
            "traffic_seed": result.traffic_seed,
            "trace_id": result.trace_id,
            "generator_version": result.generator_version,
            "frames_sent": result.frames_sent,
            "datagrams_sent": result.datagrams_sent,
            "bytes_sent": result.bytes_sent,
            "average_mbit_s": result.average_mbit_s,
            "first_send_ns": result.first_send_ns,
            "last_send_ns": result.last_send_ns,
        }

    sender_results = []
    with ThreadPoolExecutor(max_workers=max(1, len(paths))) as executor:
        futures = {executor.submit(run_path, path): path for path in paths}
        for future in as_completed(futures):
            row = future.result()
            if row.get("skipped"):
                add_event(
                    session,
                    run,
                    "video-probe-stage",
                    f"Skipping {row['path_id']}: {row['reason']}.",
                    {"path": futures[future]},
                )
                continue
            add_event(
                session,
                run,
                "video-probe-stage",
                f"UDP video frame probe completed for {row['path_id']}.",
                row,
            )
            sender_results.append(row)
    receiver_summary = {}
    if receiver_settle_seconds:
        add_event(
            session,
            run,
            "video-probe-settle",
            "Waiting for late UDP video packets before collecting receiver summary.",
            {"seconds": receiver_settle_seconds},
        )
        settle_deadline = time.monotonic() + receiver_settle_seconds
        while time.monotonic() < settle_deadline:
            if cancel_event is not None and cancel_event.is_set():
                break
            time.sleep(min(0.25, settle_deadline - time.monotonic()))
    try:
        receiver_summary = TestNodeClient(server.control_api_url).video_frame_stats(
            f"{run.run_id}-video",
            finalize=True,
            delete=True,
        )
    except Exception as exc:
        receiver_summary = {"error": str(exc), "type": type(exc).__name__}
    add_event(
        session,
        run,
        "video-probe-summary",
        "UDP video frame probe receiver summary collected.",
        receiver_summary,
    )
    joined_paths: dict[str, dict] = {}
    receiver_paths = receiver_summary.get("paths") if isinstance(receiver_summary, dict) else {}
    receiver_paths = receiver_paths if isinstance(receiver_paths, dict) else {}
    for sender in sender_results:
        path_id = str(sender.get("path_id"))
        receiver = receiver_paths.get(path_id, {})
        frames_sent = int(sender.get("frames_sent") or 0)
        frames_seen = int(receiver.get("frames_seen") or 0)
        frames_complete = int(receiver.get("frames_complete") or 0)
        frames_partial = int(
            receiver.get("frames_partial") or receiver.get("frames_incomplete") or 0
        )
        joined_paths[path_id] = {
            **sender,
            "receiver": receiver,
            "frames_seen": frames_seen,
            "frames_complete": frames_complete,
            "frames_partial": frames_partial,
            "frames_fully_lost": max(0, frames_sent - frames_seen),
            "frames_not_decodable": max(0, frames_sent - frames_complete),
            "frame_success_percent": (
                frames_complete / frames_sent * 100 if frames_sent > 0 else None
            ),
            "validity": (
                "server-confirmed"
                if int(receiver.get("datagrams_received") or 0) > 0 and frames_sent > 0
                else "sender-only"
            ),
        }
    dual_path = receiver_summary.get("dual_path") if isinstance(receiver_summary, dict) else {}
    if isinstance(dual_path, dict) and dual_path:
        max_frames_sent = max(
            (int(row.get("frames_sent") or 0) for row in sender_results),
            default=0,
        )
        complete_on_either = int(dual_path.get("complete_on_either") or 0)
        dual_path = {
            **dual_path,
            "frames_sent": max_frames_sent,
            "lost_on_both": max(0, max_frames_sent - complete_on_either),
            "effective_redundant_success_percent": (
                complete_on_either / max_frames_sent * 100 if max_frames_sent else None
            ),
        }
    has_sender_traffic = any(int(row.get("bytes_sent") or 0) > 0 for row in sender_results)
    has_receiver_traffic = any(
        int(row.get("datagrams_received") or 0) > 0 for row in receiver_paths.values()
    )
    return {
        "status": "ok" if has_sender_traffic else "skipped",
        "validity": "server-confirmed" if has_receiver_traffic else "sender-only",
        "sender_results": sender_results,
        "receiver_summary": receiver_summary,
        "dual_path": dual_path,
        "paths": joined_paths,
    }


def execute_run(
    session: Session,
    run: TestRun,
    client_factory: type[TestNodeClient] = TestNodeClient,
    cancel_event: Event | None = None,
) -> TestRun:
    router = run.router
    adapter = adapter_for(router)
    reservation: TestNodeReservation | None = None
    reservation_client: TestNodeClient | None = None
    metric_sampler: RunMetricSampler | None = None
    try:
        transition(session, run, RunState.PREFLIGHT)
        server = _server_for_run(session, run)
        _raise_if_cancelled(session, run, cancel_event)
        _capture_environment_snapshot(session, run, adapter, server, client_factory)
        _raise_if_cancelled(session, run, cancel_event)
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
            identity = check.details.get("identity") if check.ok else None
            if check.name == "mikrotik-api" and identity:
                router.display_name = str(identity)
                session.add(router)
                session.commit()
        if any(not check.ok for check in router_checks):
            transition(session, run, RunState.FAILED, "router preflight failed")
            return run

        _raise_if_cancelled(session, run, cancel_event)
        transition(session, run, RunState.VERIFYING_PATHS)
        path_checks = adapter.verify_paths()
        for check in path_checks:
            add_event(session, run, "path-verification", check.message, asdict(check))
        if any(not check.ok for check in path_checks):
            transition(session, run, RunState.FAILED, "path verification failed")
            return run

        _raise_if_cancelled(session, run, cancel_event)
        transition(session, run, RunState.WARMING_UP)
        reservation, reservation_client = _reserve_server(session, run, server, client_factory)
        transition(session, run, RunState.RUNNING)
        _raise_if_cancelled(session, run, cancel_event)
        telemetry_before = _safe_router_telemetry(session, run, adapter, "before-traffic")
        metric_sampler = _metric_sampler_for_run(session, run, server)
        if metric_sampler is not None:
            metric_sampler.set_phase("idle", "idle-latency")
            metric_sampler.start()
        latency_results = _execute_latency_stage(session, run, adapter, server)
        _raise_if_cancelled(session, run, cancel_event)
        upload_results = []
        udp_upload_results = []
        tcp_rounds = _tcp_upload_count(run)
        udp_pattern = _udp_pattern(run)
        if udp_pattern == "beginning":
            if metric_sampler is not None:
                metric_sampler.set_phase("udp", "beginning")
            udp_upload_results.extend(
                _execute_udp_upload_stage(session, run, server, "beginning", cancel_event)
            )
            _raise_if_cancelled(session, run, cancel_event)
        for round_index in range(1, tcp_rounds + 1):
            _raise_if_cancelled(session, run, cancel_event)
            if metric_sampler is not None:
                metric_sampler.set_phase("tcp", f"round-{round_index}")
            upload_results.extend(
                _execute_http_upload_stage(
                    session,
                    run,
                    server,
                    reservation_client,
                    round_index=round_index,
                    total_rounds=tcp_rounds,
                    cancel_event=cancel_event,
                )
            )
            _raise_if_cancelled(session, run, cancel_event)
            if udp_pattern == "after_each_tcp":
                if metric_sampler is not None:
                    metric_sampler.set_phase("udp", f"after-tcp-{round_index}")
                udp_upload_results.extend(
                    _execute_udp_upload_stage(
                        session, run, server, f"after-tcp-{round_index}", cancel_event
                    )
                )
                _raise_if_cancelled(session, run, cancel_event)
        if udp_pattern == "end":
            if metric_sampler is not None:
                metric_sampler.set_phase("udp", "end")
            udp_upload_results.extend(
                _execute_udp_upload_stage(session, run, server, "end", cancel_event)
            )
            _raise_if_cancelled(session, run, cancel_event)
        if metric_sampler is not None:
            metric_sampler.set_phase("video", "video-probe")
        video_probe_results = _execute_video_probe_stage(session, run, server, cancel_event)
        _raise_if_cancelled(session, run, cancel_event)
        if metric_sampler is not None:
            metric_sampler.set_phase("final_recovery", "after-traffic")
        telemetry_after = _safe_router_telemetry(session, run, adapter, "after-traffic")
        has_video_sender_traffic = any(
            int(row.get("bytes_sent") or 0) > 0
            for row in video_probe_results.get("sender_results", [])
        )
        valid_latency_results = [
            row
            for row in latency_results
            if row.get("validity") != "invalid" and int(row.get("received") or 0) > 0
        ]
        has_live_results = bool(
            upload_results
            or udp_upload_results
            or valid_latency_results
            or has_video_sender_traffic
        )
        if not has_live_results:
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
        protocol_info = run.resolved_plan.get("metadata", {}).get("protocol", {})
        comparable_protocol_ids = {"comparable-benchmark", "comparable-v1"}
        comparison_eligible = bool(
            has_live_results and protocol_info.get("protocol_id") in comparable_protocol_ids
        )
        run.summary = {
            "validity": ("live-upload" if has_live_results else "simulated"),
            "result_schema_version": run.resolved_plan.get("result_schema_version", 2),
            "protocol": protocol_info,
            "comparison_eligible": comparison_eligible,
            "exclusion_reasons": (
                []
                if comparison_eligible
                else ["exploratory_or_legacy_protocol"]
            ),
            "warnings": controller_check.warnings,
            "message": (
                "Run completed with live measured stages."
                if has_live_results
                else "MVP run completed using adapter checks and simulated measurements."
            ),
            "test_node_reserved": reservation is not None,
            "latency_results": latency_results,
            "upload_results": upload_results,
            "udp_upload_results": udp_upload_results,
            "video_probe_results": video_probe_results,
            "telemetry_before": telemetry_before,
            "telemetry_after": telemetry_after,
            "test_node_connections": connections,
        }
        run.protocol_hash = protocol_info.get("protocol_hash")
        run.result_schema_version = int(protocol_info.get("result_schema_version") or 1)
        run.comparison_eligible = comparison_eligible
        run.exclusion_reasons_json = run.summary["exclusion_reasons"]
        run.integrity_json = {
            **(run.integrity_json or {}),
            "protocol_hash_verified": bool(run.protocol_hash),
            "traffic_receiver_confirmed": has_live_results,
            "comparison_eligible": comparison_eligible,
        }
        session.add(run)
        session.commit()
        transition(session, run, RunState.GENERATING_REPORT)
    except RunCancelledError as exc:
        add_event(session, run, "cancel", str(exc))
        _transition_cancelled(session, run)
    except Exception as exc:
        add_event(session, run, "error", str(exc), {"type": type(exc).__name__})
        transition(session, run, RunState.FAILED, str(exc))
    finally:
        if metric_sampler is not None:
            metric_sampler.stop()
        try:
            _release_server(session, run, reservation, reservation_client)
        except Exception as exc:
            add_event(
                session,
                run,
                "server-release-failed",
                "Failed to release test node reservation.",
                {"type": type(exc).__name__, "error": str(exc)},
            )
    if run.state == RunState.ANALYZING:
        transition(session, run, RunState.GENERATING_REPORT)
    if run.state == RunState.GENERATING_REPORT:
        transition(session, run, RunState.COMPLETED)
    if run.state == RunState.COMPLETED:
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
