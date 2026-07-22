from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import MetricSample, RouterProfile, RunEvent, RunState, TestRun

SENSITIVE_LEGACY_COLUMNS = {"imei", "imsi", "iccid", "subscriber_number"}
RADIO_METRICS = {
    "rssi": "dBm",
    "rsrp": "dBm",
    "rsrq": "dB",
    "sinr": "dB",
    "rx_bits_per_second": "bit/s",
    "tx_bits_per_second": "bit/s",
}


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _float_value(value: str | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except ValueError:
        return None


def _path_id(row: dict[str, str]) -> str:
    return row.get("interface") or row.get("path_label") or "unknown"


def _telemetry_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if value not in (None, "") and key not in SENSITIVE_LEGACY_COLUMNS
    }


def _upload_result(row: dict[str, str]) -> dict[str, Any] | None:
    speed = _float_value(row.get("upload_speed_mbit_s"))
    if speed is None:
        bytes_per_second = _float_value(row.get("upload_speed_bytes_s"))
        speed = bytes_per_second * 8 / 1_000_000 if bytes_per_second is not None else None
    if speed is None:
        return None
    return {
        "path_id": _path_id(row),
        "iteration": row.get("iteration"),
        "source": "legacy_csv",
        "url": row.get("url"),
        "file_size_bytes": _float_value(row.get("file_size_bytes")),
        "curl_exit_code": row.get("curl_exit_code"),
        "http_code": row.get("http_code"),
        "time_total_seconds": _float_value(row.get("upload_time_total_s")),
        "speed_upload_mbit_s": speed,
        "size_upload_bytes": _float_value(row.get("upload_size_bytes")),
        "validity": "legacy_sender_side",
    }


def import_legacy_upload_csv(
    session: Session,
    *,
    csv_path: Path,
    router_slug: str,
) -> list[TestRun]:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        raise ValueError(f"unknown router: {router_slug}")
    rows = list(csv.DictReader(csv_path.open(newline="")))
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        run_id = row.get("run_id") or csv_path.stem
        grouped[str(run_id)].append(row)

    imported_runs = []
    for legacy_run_id, run_rows in sorted(grouped.items()):
        run_id = f"legacy-{legacy_run_id}"
        existing = session.scalar(select(TestRun).where(TestRun.run_id == run_id))
        if existing is not None:
            imported_runs.append(existing)
            continue
        timestamps = [
            parsed for row in run_rows if (parsed := _parse_timestamp(row.get("timestamp_utc")))
        ]
        upload_results = [result for row in run_rows if (result := _upload_result(row)) is not None]
        telemetry_rows = [_telemetry_row(row) for row in run_rows]
        run = TestRun(
            run_id=run_id,
            router_id=router.id,
            plan_slug="legacy-upload-csv",
            state=RunState.COMPLETED,
            resolved_plan={
                "protocol_id": "legacy-upload-csv",
                "metadata": {
                    "source": {
                        "kind": "legacy_csv",
                        "path": str(csv_path),
                        "legacy_run_id": legacy_run_id,
                    }
                },
            },
            summary={
                "validity": "legacy_import",
                "comparison_eligible": False,
                "exclusion_reasons": ["legacy_schema_v1", "legacy_sender_side"],
                "upload_results": upload_results,
                "telemetry_after": [
                    row for row in telemetry_rows if row.get("phase") in {"after", "final"}
                ],
                "legacy_row_count": len(run_rows),
            },
            protocol_hash="legacy",
            result_schema_version=1,
            comparison_eligible=False,
            exclusion_reasons_json=["legacy_schema_v1", "legacy_sender_side"],
            environment_snapshot_json={
                "source": {
                    "kind": "legacy_csv",
                    "path": str(csv_path),
                    "legacy_run_id": legacy_run_id,
                },
                "privacy": "raw modem identifiers omitted from import",
            },
            integrity_json={
                "comparison_eligible": False,
                "exclusion_reasons": ["legacy_schema_v1", "legacy_sender_side"],
            },
            created_at=min(timestamps) if timestamps else utc_now(),
            updated_at=max(timestamps) if timestamps else utc_now(),
        )
        session.add(run)
        session.flush()
        session.add(
            RunEvent(
                run_pk=run.id,
                event_type="legacy-import",
                message="Legacy upload CSV imported as comparison-ineligible schema v1 data.",
                details={"path": str(csv_path), "rows": len(run_rows)},
            )
        )
        _add_radio_metric_samples(session, run, run_rows, timestamps)
        imported_runs.append(run)
    session.commit()
    return imported_runs


def _add_radio_metric_samples(
    session: Session,
    run: TestRun,
    rows: list[dict[str, str]],
    timestamps: list[datetime],
) -> None:
    start = min(timestamps) if timestamps else None
    for row in rows:
        timestamp = _parse_timestamp(row.get("timestamp_utc"))
        if timestamp is None:
            continue
        offset_ms = int((timestamp - start).total_seconds() * 1000) if start else 0
        for metric_name, unit in RADIO_METRICS.items():
            value = _float_value(row.get(metric_name))
            if value is None:
                continue
            session.add(
                MetricSample(
                    run_pk=run.id,
                    timestamp=timestamp,
                    offset_ms=offset_ms,
                    path_id=_path_id(row),
                    phase=row.get("phase") or "legacy",
                    metric_name=f"radio_{metric_name}",
                    value=value,
                    unit=unit,
                    validity="legacy_import",
                    details_json={"source": "legacy_csv"},
                )
            )
