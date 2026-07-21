import json
from pathlib import Path

from ltap_testbench.core.config import get_settings
from ltap_testbench.db.models import TestRun


def run_artifact_dir(run: TestRun, root: Path | None = None) -> Path:
    base = root if root is not None else get_settings().data_dir / "results"
    return base / run.run_id


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def run_report_payload(run: TestRun) -> dict:
    events = [
        {
            "timestamp": event.timestamp,
            "type": event.event_type,
            "message": event.message,
            "details": event.details,
        }
        for event in run.events
    ]
    connections = run.summary.get("test_node_connections") or run.summary.get("connections") or []
    return {
        "run_id": run.run_id,
        "router": {
            "slug": run.router.slug,
            "name": run.router.display_name,
            "kind": run.router.kind,
        },
        "plan": {
            "slug": run.plan_slug,
            "definition": run.resolved_plan,
        },
        "state": run.state,
        "state_reason": run.state_reason,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "summary": run.summary,
        "events": events,
        "connections": connections,
    }


def _format_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _format_float(value: object, digits: int = 2) -> str:
    if not isinstance(value, int | float | str):
        return _format_value(value)
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _format_value(value)


def render_markdown_report(payload: dict) -> str:
    router = payload["router"]
    plan = payload["plan"]
    summary = payload["summary"]
    lines = [
        f"# LtAP Test Run {payload['run_id']}",
        "",
        "## Overview",
        "",
        f"- Router: `{router['slug']}` ({router['name']}, {router['kind']})",
        f"- Plan: `{plan['slug']}`",
        f"- State: `{payload['state']}`",
        f"- State reason: {_format_value(payload['state_reason']) or 'none'}",
        f"- Created: {_format_value(payload['created_at'])}",
        f"- Updated: {_format_value(payload['updated_at'])}",
        "",
        "## Summary",
        "",
    ]
    if summary:
        for key, value in sorted(summary.items()):
            if isinstance(value, list | dict):
                rendered = json.dumps(value, indent=2, default=str)
                lines.extend([f"### {key}", "", "```json", rendered, "```", ""])
            else:
                lines.append(f"- {key}: {_format_value(value)}")
        lines.append("")
    else:
        lines.extend(["No summary recorded.", ""])

    upload_results = summary.get("upload_results") or []
    lines.extend(["## TCP Upload Results", ""])
    if upload_results:
        lines.extend(
            [
                "| Path | Port | Bytes | Duration s | Speed Mbit/s | Connect s | Server source |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for result in upload_results:
            connections_for_result = result.get("test_node_connections") or []
            source = connections_for_result[0].get("source") if connections_for_result else ""
            duration = result.get("time_total_seconds") or result.get("server_duration_seconds")
            speed = result.get("speed_upload_mbit_s") or result.get("server_average_mbit_s")
            row = "| {path} | {port} | {bytes} | {duration} | {speed} | {connect} | {source} |"
            lines.append(
                row.format(
                    path=_format_value(result.get("path_id")),
                    port=_format_value(result.get("remote_port") or result.get("target_port")),
                    bytes=_format_value(
                        result.get("size_upload_bytes") or result.get("server_bytes_received")
                    ),
                    duration=_format_float(duration),
                    speed=_format_float(speed),
                    connect=_format_float(result.get("time_connect_seconds"), 3),
                    source=_format_value(source),
                )
            )
        lines.append("")
    else:
        lines.extend(["No TCP upload results were recorded.", ""])

    udp_results = summary.get("udp_upload_results") or []
    lines.extend(["## UDP Upload Results", ""])
    if udp_results:
        lines.extend(
            [
                (
                    "| Path | Port | Duration s | Target Mbit/s | Sent Mbit/s | "
                    "Datagrams | Bytes | Validity |"
                ),
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for result in udp_results:
            row = (
                "| {path} | {port} | {duration} | {target} | {speed} | "
                "{datagrams} | {bytes} | {validity} |"
            )
            lines.append(
                row.format(
                    path=_format_value(result.get("path_id")),
                    port=_format_value(result.get("target_port")),
                    duration=_format_float(result.get("duration_seconds")),
                    target=_format_float(result.get("configured_bitrate_mbit_s")),
                    speed=_format_float(result.get("average_mbit_s")),
                    datagrams=_format_value(result.get("datagrams_sent")),
                    bytes=_format_value(result.get("bytes_sent")),
                    validity=_format_value(result.get("validity")),
                )
            )
        lines.append("")
    else:
        lines.extend(["No UDP upload results were recorded.", ""])

    video_probe = summary.get("video_probe_results") or {}
    receiver_summary = video_probe.get("receiver_summary") or {}
    video_paths = video_probe.get("paths") or {}
    lines.extend(["## UDP Video Frame Probe", ""])
    if video_paths or receiver_summary.get("paths"):
        lines.extend(
            [
                (
                    "| Path | Source | Sent | Seen | Complete | Partial | Fully lost | "
                    "Not decodable | Success % | p95 fragment span ms |"
                ),
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        rows = video_paths or receiver_summary.get("paths", {})
        for path_id, row in sorted(rows.items()):
            receiver = row.get("receiver") or row
            lines.append(
                (
                    "| {path} | {source} | {sent} | {seen} | {complete} | {partial} | "
                    "{lost} | {not_decodable} | {success} | {p95} |"
                ).format(
                    path=_format_value(path_id),
                    source=_format_value(receiver.get("source")),
                    sent=_format_value(row.get("frames_sent")),
                    seen=_format_value(row.get("frames_seen")),
                    complete=_format_value(row.get("frames_complete")),
                    partial=_format_value(row.get("frames_partial")),
                    lost=_format_value(row.get("frames_fully_lost")),
                    not_decodable=_format_value(row.get("frames_not_decodable")),
                    success=_format_float(row.get("frame_success_percent")),
                    p95=_format_float(
                        receiver.get("fragment_arrival_span_ms_p95")
                        or receiver.get("frame_completion_ms_p95")
                    ),
                )
            )
        winners = receiver_summary.get("first_arrival_winners") or {}
        lines.extend(
            [
                "",
                (
                    "- Paired complete frames: "
                    f"{_format_value(receiver_summary.get('paired_frames_complete'))}"
                ),
                f"- First-arrival winners: `{json.dumps(winners, sort_keys=True)}`",
                (
                    "- First-arrival ties: "
                    f"{_format_value(receiver_summary.get('first_arrival_ties'))}"
                ),
                (
                    "- p95 corrected path arrival difference ms: "
                    f"{_format_float(receiver_summary.get('corrected_path_arrival_delta_ms_p95'))}"
                ),
                (
                    "- p95 raw path arrival difference ms: "
                    f"{_format_float(receiver_summary.get('path_arrival_delta_ms_p95'))}"
                ),
                "",
            ]
        )
    else:
        lines.extend(["No UDP video frame probe results were recorded.", ""])

    latency_results = summary.get("latency_results") or []
    lines.extend(["## Latency Results", ""])
    if latency_results:
        lines.extend(
            [
                "| Path | Target | Sent | Received | Loss % | Avg ms | Min ms | Max ms |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for result in latency_results:
            row = "| {path} | {target} | {sent} | {received} | {loss} | {avg} | {min} | {max} |"
            lines.append(
                row.format(
                    path=_format_value(result.get("path_id")),
                    target=_format_value(result.get("target_host")),
                    sent=_format_value(result.get("sent")),
                    received=_format_value(result.get("received")),
                    loss=_format_float(result.get("loss_percent")),
                    avg=_format_float(result.get("avg_ms")),
                    min=_format_float(result.get("min_ms")),
                    max=_format_float(result.get("max_ms")),
                )
            )
        lines.append("")
    else:
        lines.extend(["No latency results were recorded.", ""])

    telemetry_after = summary.get("telemetry_after") or []
    lines.extend(["## LTE Telemetry", ""])
    if telemetry_after:
        lines.extend(
            [
                "| Path | Status | Operator | Band | RSRP | RSRQ | SINR | TX rate | RX rate |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in telemetry_after:
            table_row = (
                "| {path} | {status} | {operator} | {band} | {rsrp} | {rsrq} | "
                "{sinr} | {tx} | {rx} |"
            )
            lines.append(
                table_row.format(
                    path=_format_value(row.get("path_id")),
                    status=_format_value(row.get("status")),
                    operator=_format_value(row.get("operator")),
                    band=_format_value(row.get("primary_band")),
                    rsrp=_format_value(row.get("rsrp")),
                    rsrq=_format_value(row.get("rsrq")),
                    sinr=_format_value(row.get("sinr")),
                    tx=_format_value(row.get("tx_rate")),
                    rx=_format_value(row.get("rx_rate")),
                )
            )
        lines.append("")
    else:
        lines.extend(["No LTE telemetry snapshots were recorded.", ""])

    connections = payload.get("connections") or []
    lines.extend(["## Test Node Connections", ""])
    if connections:
        lines.extend(
            [
                "| Source | Port | Bytes | Duration s | Average Mbit/s |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for connection in connections:
            lines.append(
                "| {source} | {port} | {bytes} | {duration} | {mbit} |".format(
                    source=_format_value(connection.get("source")),
                    port=_format_value(connection.get("destination_port")),
                    bytes=_format_value(connection.get("bytes_received")),
                    duration=_format_value(connection.get("duration_seconds")),
                    mbit=_format_value(connection.get("average_mbit_s")),
                )
            )
        lines.append("")
    else:
        lines.extend(["No test-node connection records were attached to this run.", ""])

    lines.extend(["## Event Timeline", ""])
    if payload["events"]:
        lines.extend(["| Time | Type | Message |", "| --- | --- | --- |"])
        for event in payload["events"]:
            lines.append(
                f"| {_format_value(event['timestamp'])} | `{event['type']}` | {event['message']} |"
            )
        lines.append("")
    else:
        lines.extend(["No events recorded.", ""])

    return "\n".join(lines).rstrip() + "\n"


def persist_run_artifacts(run: TestRun, root: Path | None = None) -> dict[str, str]:
    directory = run_artifact_dir(run, root)
    directory.mkdir(parents=True, exist_ok=True)

    metadata_path = directory / "metadata.json"
    plan_path = directory / "resolved_test_plan.json"
    summary_path = directory / "summary.json"
    events_path = directory / "events.jsonl"
    report_json_path = directory / "report.json"
    report_markdown_path = directory / "report.md"

    write_json(
        metadata_path,
        {
            "run_id": run.run_id,
            "router": run.router.slug,
            "router_kind": run.router.kind,
            "plan_slug": run.plan_slug,
            "state": run.state,
            "state_reason": run.state_reason,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
    )
    write_json(plan_path, run.resolved_plan)
    write_json(summary_path, run.summary)
    with events_path.open("w") as event_file:
        for event in run.events:
            event_file.write(
                json.dumps(
                    {
                        "timestamp": event.timestamp,
                        "type": event.event_type,
                        "message": event.message,
                        "details": event.details,
                    },
                    default=str,
                )
                + "\n"
            )

    report_payload = run_report_payload(run)
    write_json(report_json_path, report_payload)
    report_markdown_path.write_text(render_markdown_report(report_payload))

    return {
        "directory": str(directory),
        "metadata": str(metadata_path),
        "resolved_test_plan": str(plan_path),
        "summary": str(summary_path),
        "events": str(events_path),
        "report_json": str(report_json_path),
        "report_markdown": str(report_markdown_path),
    }


def list_run_artifacts(run: TestRun) -> list[dict[str, str | int]]:
    directory = run_artifact_dir(run)
    if not directory.exists():
        return []
    artifacts: list[dict[str, str | int]] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        artifacts.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(directory)),
                "bytes": path.stat().st_size,
            }
        )
    return artifacts
