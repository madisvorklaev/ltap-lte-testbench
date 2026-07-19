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


def persist_run_artifacts(run: TestRun, root: Path | None = None) -> dict[str, str]:
    directory = run_artifact_dir(run, root)
    directory.mkdir(parents=True, exist_ok=True)

    metadata_path = directory / "metadata.json"
    plan_path = directory / "resolved_test_plan.json"
    summary_path = directory / "summary.json"
    events_path = directory / "events.jsonl"

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

    return {
        "directory": str(directory),
        "metadata": str(metadata_path),
        "resolved_test_plan": str(plan_path),
        "summary": str(summary_path),
        "events": str(events_path),
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
