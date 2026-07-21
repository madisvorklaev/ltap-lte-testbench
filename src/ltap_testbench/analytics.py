from __future__ import annotations

from statistics import median
from typing import Any

from ltap_testbench.db.models import TestRun
from ltap_testbench.profiles.protocols import protocol_metadata


def float_value(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    index = min(len(clean) - 1, max(0, round((len(clean) - 1) * pct)))
    return clean[index]


def aggregate(values: list[float | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"n": 0}
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return {
        "n": len(clean),
        "mean": mean,
        "median": median(clean),
        "p10": percentile(clean, 0.10),
        "p25": percentile(clean, 0.25),
        "p75": percentile(clean, 0.75),
        "p90": percentile(clean, 0.90),
        "p95": percentile(clean, 0.95),
        "min": min(clean),
        "max": max(clean),
        "stddev": variance**0.5,
    }


def lab_metadata(run: TestRun) -> dict[str, Any]:
    if not run.resolved_plan:
        return {}
    metadata = run.resolved_plan.get("metadata", {})
    lab = metadata.get("lab", {}) if isinstance(metadata, dict) else {}
    if not lab and run.resolved_plan:
        lab = run.resolved_plan.get("lab", {})
    return lab if isinstance(lab, dict) else {}


def protocol_info(run: TestRun) -> dict[str, Any]:
    summary = run.summary or {}
    if isinstance(summary.get("protocol"), dict) and summary["protocol"].get("protocol_hash"):
        return summary["protocol"]
    metadata = run.resolved_plan.get("metadata", {}) if run.resolved_plan else {}
    if isinstance(metadata.get("protocol"), dict) and metadata["protocol"].get("protocol_hash"):
        return metadata["protocol"]
    if run.resolved_plan:
        return protocol_metadata(run.resolved_plan)
    return {
        "protocol_id": "legacy",
        "protocol_version": "1",
        "protocol_hash": "legacy",
        "result_schema_version": 1,
    }


def known_path_ids(run: TestRun) -> list[str]:
    path_ids = []
    for path in run.router.metadata_json.get("paths", []) if run.router.metadata_json else []:
        path_id = path.get("id")
        if path_id:
            path_ids.append(str(path_id))
    summary = run.summary or {}
    for key in ("latency_results", "upload_results", "udp_upload_results"):
        for row in summary.get(key, []) if summary else []:
            path_id = row.get("path_id")
            if path_id and str(path_id) not in path_ids:
                path_ids.append(str(path_id))
    video_paths = (summary.get("video_probe_results") or {}).get("paths", {}) if summary else {}
    for path_id in video_paths:
        if str(path_id) not in path_ids:
            path_ids.append(str(path_id))
    return path_ids or ["lte1", "lte2"]


def _udp_receiver_mbit(row: dict[str, Any]) -> float | None:
    receiver_value = row.get("receiver")
    receiver: dict[str, Any] = receiver_value if isinstance(receiver_value, dict) else {}
    return (
        float_value(receiver.get("delivered_mbit_s"))
        or float_value(row.get("server_average_mbit_s"))
        or _legacy_udp_connection_mbit(row)
    )


def _legacy_udp_connection_mbit(row: dict[str, Any]) -> float | None:
    values = [
        float_value(connection.get("delivered_mbit_s") or connection.get("average_mbit_s"))
        for connection in row.get("test_node_connections", [])
        if connection.get("protocol") == "udp"
    ]
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _udp_loss(row: dict[str, Any]) -> float | None:
    delivery_value = row.get("delivery")
    delivery: dict[str, Any] = delivery_value if isinstance(delivery_value, dict) else {}
    return (
        float_value(delivery.get("packet_loss_percent"))
        or float_value(row.get("packet_loss_percent"))
    )


def analytics_run_row(run: TestRun) -> dict[str, Any]:
    lab = lab_metadata(run)
    summary = run.summary or {}
    protocol = protocol_info(run)
    paths: dict[str, dict[str, Any]] = {
        path_id: {
            "tcp_mbit_s": None,
            "udp_mbit_s": None,
            "udp_loss_percent": None,
            "latency_avg_ms": None,
            "latency_loss_percent": None,
            "video_success_percent": None,
            "video_not_decodable": None,
        }
        for path_id in known_path_ids(run)
    }
    for path_id in paths:
        tcp_rows = [
            row for row in summary.get("upload_results", []) if str(row.get("path_id")) == path_id
        ]
        udp_rows = [
            row
            for row in summary.get("udp_upload_results", [])
            if str(row.get("path_id")) == path_id
        ]
        latency_rows = [
            row for row in summary.get("latency_results", []) if str(row.get("path_id")) == path_id
        ]
        paths[path_id]["tcp_mbit_s"] = aggregate(
            [
                float_value(row.get("server_average_mbit_s") or row.get("speed_upload_mbit_s"))
                for row in tcp_rows
            ]
        ).get("median")
        paths[path_id]["udp_mbit_s"] = aggregate([_udp_receiver_mbit(row) for row in udp_rows]).get(
            "median"
        )
        paths[path_id]["udp_loss_percent"] = aggregate([_udp_loss(row) for row in udp_rows]).get(
            "median"
        )
        if latency_rows:
            latest_latency = latency_rows[-1]
            paths[path_id]["latency_avg_ms"] = float_value(latest_latency.get("avg_ms"))
            paths[path_id]["latency_loss_percent"] = float_value(latest_latency.get("loss_percent"))
    video_results = summary.get("video_probe_results") or {}
    for path_id, row in (video_results.get("paths") or {}).items():
        path = paths.setdefault(str(path_id), {})
        path["video_success_percent"] = float_value(row.get("frame_success_percent"))
        path["video_not_decodable"] = float_value(row.get("frames_not_decodable"))
    dual_video = video_results.get("dual_path") or (
        video_results.get("receiver_summary") or {}
    ).get("dual_path") or {}
    comparison_eligible = bool(summary.get("comparison_eligible"))
    exclusion_reasons = list(summary.get("exclusion_reasons") or [])
    if not comparison_eligible and not exclusion_reasons:
        exclusion_reasons = ["legacy_or_custom_run"]
    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "router": run.router.slug,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_version": protocol.get("protocol_version"),
        "protocol_hash": protocol.get("protocol_hash"),
        "result_schema_version": protocol.get("result_schema_version"),
        "experiment_id": run.experiment_id,
        "variant_id": run.variant_id,
        "batch_id": run.batch_id,
        "comparison_eligible": comparison_eligible,
        "exclusion_reasons": exclusion_reasons,
        "antenna": lab.get("antenna") or "",
        "antenna_profile_id": lab.get("antenna_profile_id") or "",
        "antenna_gain_dbi": lab.get("antenna_gain_dbi"),
        "antenna_effective_gain_dbi": lab.get("antenna_effective_gain_dbi"),
        "tcp_file_size_mb": lab.get("tcp_file_size_mb"),
        "tcp_mode": lab.get("tcp_mode"),
        "tcp_upload_count": lab.get("tcp_upload_count"),
        "udp_duration_seconds": lab.get("udp_duration_seconds"),
        "udp_bitrate_mbit_s": lab.get("udp_bitrate_mbit_s"),
        "udp_pattern": lab.get("udp_pattern"),
        "video_duration_seconds": lab.get("video_duration_seconds"),
        "video_resolution": lab.get("video_resolution"),
        "video_fps": lab.get("video_fps"),
        "video_scenario": lab.get("video_scenario"),
        "validity": summary.get("validity"),
        "dual_video": dual_video,
        "paths": paths,
    }


def _path_metric(row: dict[str, Any], metric_name: str, path_id: str) -> float | None:
    return float_value(row.get("paths", {}).get(path_id, {}).get(metric_name))


def _metric_policy(metric_name: str) -> dict[str, Any]:
    if metric_name in {"latency_avg_ms"}:
        return {"higher_is_better": False, "absolute_threshold": 10.0, "relative_threshold": 0.15}
    if metric_name in {"udp_loss_percent"}:
        return {"higher_is_better": False, "absolute_threshold": 0.2, "relative_threshold": 0.0}
    return {"higher_is_better": True, "absolute_threshold": 0.0, "relative_threshold": 0.10}


def compare_cohorts(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    metric_name: str,
    path_id: str,
    min_runs: int = 5,
) -> dict[str, Any]:
    baseline_hashes = {
        str(row.get("protocol_hash")) for row in baseline_rows if row.get("protocol_hash")
    }
    candidate_hashes = {
        str(row.get("protocol_hash")) for row in candidate_rows if row.get("protocol_hash")
    }
    hashes = sorted(baseline_hashes | candidate_hashes)
    baseline_values = [_path_metric(row, metric_name, path_id) for row in baseline_rows]
    candidate_values = [_path_metric(row, metric_name, path_id) for row in candidate_rows]
    baseline = aggregate(baseline_values)
    candidate = aggregate(candidate_values)
    policy = _metric_policy(metric_name)
    conclusion: dict[str, Any] = {
        "status": "INCONCLUSIVE",
        "reason": "minimum sample count was not met",
    }
    if not baseline_rows or not candidate_rows:
        conclusion = {"status": "NO_DATA", "reason": "one or both cohorts are empty"}
    elif len(hashes) != 1:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "baseline and candidate use different protocol hashes",
        }
    elif int(baseline.get("n") or 0) < min_runs or int(candidate.get("n") or 0) < min_runs:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": f"fewer than {min_runs} metric-bearing runs per cohort",
        }
    elif baseline.get("median") is not None and candidate.get("median") is not None:
        baseline_median = float(baseline["median"])
        candidate_median = float(candidate["median"])
        delta = candidate_median - baseline_median
        relative_delta = delta / baseline_median if baseline_median else None
        threshold = max(
            float(policy["absolute_threshold"]),
            abs(baseline_median) * float(policy["relative_threshold"]),
        )
        beneficial_delta = delta if policy["higher_is_better"] else -delta
        if beneficial_delta >= threshold:
            conclusion = {
                "status": "LIKELY_IMPROVEMENT",
                "reason": "median delta exceeds the practical threshold",
            }
        elif beneficial_delta <= -threshold:
            conclusion = {
                "status": "LIKELY_REGRESSION",
                "reason": "median delta exceeds the practical threshold in the negative direction",
            }
        else:
            conclusion = {
                "status": "INCONCLUSIVE",
                "reason": "median delta is below the practical threshold",
            }
        conclusion["delta"] = delta
        conclusion["relative_delta"] = relative_delta
        conclusion["practical_threshold"] = threshold
    return {
        "metric": metric_name,
        "path_id": path_id,
        "min_runs": min_runs,
        "protocol_hashes": hashes,
        "baseline": baseline,
        "candidate": candidate,
        "policy": policy,
        "conclusion": conclusion,
        "baseline_run_ids": [row.get("run_id") for row in baseline_rows],
        "candidate_run_ids": [row.get("run_id") for row in candidate_rows],
    }


def cohort_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    compatible_rows = [row for row in rows if row.get("comparison_eligible")]
    hashes = sorted({str(row.get("protocol_hash")) for row in rows if row.get("protocol_hash")})
    metric_rows = compatible_rows if compatible_rows else rows
    metrics: dict[str, Any] = {}
    for path_id in sorted({path_id for row in metric_rows for path_id in row.get("paths", {})}):
        metrics[path_id] = {
            "tcp_mbit_s": aggregate(
                [
                    float_value(row.get("paths", {}).get(path_id, {}).get("tcp_mbit_s"))
                    for row in metric_rows
                ]
            ),
            "udp_mbit_s": aggregate(
                [
                    float_value(row.get("paths", {}).get(path_id, {}).get("udp_mbit_s"))
                    for row in metric_rows
                ]
            ),
            "latency_avg_ms": aggregate(
                [
                    float_value(row.get("paths", {}).get(path_id, {}).get("latency_avg_ms"))
                    for row in metric_rows
                ]
            ),
            "video_success_percent": aggregate(
                [
                    float_value(
                        row.get("paths", {}).get(path_id, {}).get("video_success_percent")
                    )
                    for row in metric_rows
                ]
            ),
        }
    minimum_evidence_met = len(compatible_rows) >= 5 and len(hashes) == 1
    if not rows:
        conclusion = {"status": "NO_DATA", "reason": "no runs matched the selected filters"}
    elif len(hashes) > 1:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "selected runs use multiple protocol hashes",
        }
    elif len(compatible_rows) < 5:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "fewer than five comparable runs matched the selected filters",
        }
    else:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "baseline and candidate cohorts are not selected yet",
        }
    return {
        "run_count": len(rows),
        "eligible_run_count": len(compatible_rows),
        "metric_run_count": len(metric_rows),
        "protocol_hashes": hashes,
        "mixed_protocols": len(hashes) > 1,
        "metrics": metrics,
        "minimum_evidence_met": minimum_evidence_met,
        "conclusion": conclusion,
    }
