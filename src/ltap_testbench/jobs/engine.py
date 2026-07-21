import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from ltap_testbench.routers.base import RouterAdapter
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight
from ltap_testbench.testnode.client import TestNodeClient, TestNodeReservation
from ltap_testbench.traffic.commands import run_command
from ltap_testbench.traffic.http_upload import parse_curl_write_out
from ltap_testbench.traffic.tcp_upload import run_timed_tcp_upload
from ltap_testbench.traffic.udp_upload import run_udp_upload
from ltap_testbench.traffic.video_udp import run_video_udp_probe

TCP_UPLOAD_STAGE = "tcp-upload"
UDP_UPLOAD_STAGE = "udp-upload"
VIDEO_PROBE_STAGE = "video-udp-probe"


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
    return TCP_UPLOAD_STAGE in {str(stage) for stage in stages}


def _plan_has_udp_upload_stage(run: TestRun) -> bool:
    stages = run.resolved_plan.get("stages", [])
    return UDP_UPLOAD_STAGE in {str(stage) for stage in stages}


def _plan_has_latency_stage(run: TestRun) -> bool:
    stages = run.resolved_plan.get("stages", [])
    return any("latency" in str(stage) for stage in stages)


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
    stages = run.resolved_plan.get("stages", [])
    return VIDEO_PROBE_STAGE in {str(stage) for stage in stages}


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
            )
            summary = parse_curl_write_out(result.stdout)
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
        )
        connections = []
        if server.public_host and server:
            try:
                connections = TestNodeClient(server.control_api_url).run_connections(udp_run_id)
            except Exception:
                connections = []
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
        time.sleep(receiver_settle_seconds)
    try:
        receiver_summary = TestNodeClient(server.control_api_url).video_frame_stats(
            f"{run.run_id}-video"
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
    has_sender_traffic = any(int(row.get("bytes_sent") or 0) > 0 for row in sender_results)
    has_receiver_traffic = any(
        int(row.get("datagrams_received") or 0) > 0 for row in receiver_paths.values()
    )
    return {
        "status": "ok" if has_sender_traffic else "skipped",
        "validity": "server-confirmed" if has_receiver_traffic else "sender-only",
        "sender_results": sender_results,
        "receiver_summary": receiver_summary,
        "paths": joined_paths,
    }


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
            identity = check.details.get("identity") if check.ok else None
            if check.name == "mikrotik-api" and identity:
                router.display_name = str(identity)
                session.add(router)
                session.commit()
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
        telemetry_before = _safe_router_telemetry(session, run, adapter, "before-traffic")
        latency_results = _execute_latency_stage(session, run, adapter, server)
        upload_results = []
        udp_upload_results = []
        tcp_rounds = _tcp_upload_count(run)
        udp_pattern = _udp_pattern(run)
        if udp_pattern == "beginning":
            udp_upload_results.extend(_execute_udp_upload_stage(session, run, server, "beginning"))
        for round_index in range(1, tcp_rounds + 1):
            upload_results.extend(
                _execute_http_upload_stage(
                    session,
                    run,
                    server,
                    reservation_client,
                    round_index=round_index,
                    total_rounds=tcp_rounds,
                )
            )
            if udp_pattern == "after_each_tcp":
                udp_upload_results.extend(
                    _execute_udp_upload_stage(session, run, server, f"after-tcp-{round_index}")
                )
        if udp_pattern == "end":
            udp_upload_results.extend(_execute_udp_upload_stage(session, run, server, "end"))
        video_probe_results = _execute_video_probe_stage(session, run, server)
        telemetry_after = _safe_router_telemetry(session, run, adapter, "after-traffic")
        has_video_sender_traffic = any(
            int(row.get("bytes_sent") or 0) > 0
            for row in video_probe_results.get("sender_results", [])
        )
        has_live_results = bool(
            upload_results or udp_upload_results or latency_results or has_video_sender_traffic
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
        run.summary = {
            "validity": ("live-upload" if has_live_results else "simulated"),
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
        session.add(run)
        session.commit()
        transition(session, run, RunState.GENERATING_REPORT)
        persist_run_artifacts(run)
        transition(session, run, RunState.COMPLETED)
    except Exception as exc:
        add_event(session, run, "error", str(exc), {"type": type(exc).__name__})
        transition(session, run, RunState.FAILED, str(exc))
    finally:
        _release_server(session, run, reservation, reservation_client)
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
