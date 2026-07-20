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
