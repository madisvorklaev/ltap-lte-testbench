from __future__ import annotations

import random
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from ltap_testbench.db.models import TestRun
from ltap_testbench.profiles.protocols import protocol_metadata

COMPATIBILITY_FIELDS = (
    "protocol_hash",
    "result_schema_version",
    "application_measurement_version",
    "test_node_version",
    "site_id",
    "path_count",
)
LOCAL_TIMEZONE = ZoneInfo("Europe/Tallinn")


def float_value(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    index = min(len(clean) - 1, max(0, round((len(clean) - 1) * pct)))
    return clean[index]


def _local_hour(created_at: Any) -> float | None:
    if created_at is None:
        return None
    try:
        local_time = created_at.astimezone(LOCAL_TIMEZONE)
    except (AttributeError, ValueError):
        return None
    return local_time.hour + local_time.minute / 60


def aggregate(values: list[float | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"n": 0}
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    p25 = percentile(clean, 0.25)
    p75 = percentile(clean, 0.75)
    return {
        "n": len(clean),
        "mean": mean,
        "median": median(clean),
        "p10": percentile(clean, 0.10),
        "p25": p25,
        "p75": p75,
        "iqr": (p75 - p25) if p25 is not None and p75 is not None else None,
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
    return first_present(
        float_value(receiver.get("delivered_mbit_s")),
        float_value(row.get("server_average_mbit_s")),
        _legacy_udp_connection_mbit(row),
    )


def _legacy_udp_connection_mbit(row: dict[str, Any]) -> float | None:
    values = [
        first_present(
            float_value(connection.get("delivered_mbit_s")),
            float_value(connection.get("average_mbit_s")),
        )
        for connection in row.get("test_node_connections", [])
        if connection.get("protocol") == "udp"
    ]
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _udp_loss(row: dict[str, Any]) -> float | None:
    delivery_value = row.get("delivery")
    delivery: dict[str, Any] = delivery_value if isinstance(delivery_value, dict) else {}
    return first_present(
        float_value(delivery.get("packet_loss_percent")),
        float_value(row.get("packet_loss_percent")),
    )


def analytics_run_row(run: TestRun) -> dict[str, Any]:
    lab = lab_metadata(run)
    summary = run.summary or {}
    protocol = protocol_info(run)
    environment = run.environment_snapshot_json or {}
    site_id = (
        (run.resolved_plan.get("site_id") if run.resolved_plan else None)
        or lab.get("site_id")
        or environment.get("site_id")
    )
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
                first_present(
                    float_value(row.get("server_average_mbit_s")),
                    float_value(row.get("speed_upload_mbit_s")),
                )
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
    dual_video = (
        video_results.get("dual_path")
        or (video_results.get("receiver_summary") or {}).get("dual_path")
        or {}
    )
    comparison_eligible = bool(run.comparison_eligible or summary.get("comparison_eligible"))
    exclusion_reasons = list(run.exclusion_reasons_json or summary.get("exclusion_reasons") or [])
    if not comparison_eligible and not exclusion_reasons:
        exclusion_reasons = ["legacy_or_custom_run"]
    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "router": run.router.slug,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "local_hour": _local_hour(run.created_at),
        "local_date": run.created_at.astimezone(LOCAL_TIMEZONE).date().isoformat()
        if run.created_at
        else None,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_version": protocol.get("protocol_version"),
        "protocol_hash": protocol.get("protocol_hash"),
        "result_schema_version": protocol.get("result_schema_version"),
        "application_version": run.application_version,
        "application_git_commit": run.application_git_commit,
        "application_measurement_version": run.application_git_commit or run.application_version,
        "test_node_version": run.test_node_version
        or (environment.get("test_node") or {}).get("version")
        or ((environment.get("test_node") or {}).get("health") or {}).get("version"),
        "site_id": site_id,
        "path_count": len(paths),
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


def _bootstrap_median_delta_ci(
    baseline_values: list[float | None],
    candidate_values: list[float | None],
    *,
    iterations: int = 1000,
    seed: int = 1001,
) -> dict[str, Any] | None:
    baseline_clean = [float(value) for value in baseline_values if value is not None]
    candidate_clean = [float(value) for value in candidate_values if value is not None]
    if not baseline_clean or not candidate_clean:
        return None
    rng = random.Random(seed)
    deltas = []
    for _index in range(iterations):
        baseline_sample = [rng.choice(baseline_clean) for _row in baseline_clean]
        candidate_sample = [rng.choice(candidate_clean) for _row in candidate_clean]
        deltas.append(median(candidate_sample) - median(baseline_sample))
    return {
        "low": float(percentile(deltas, 0.025) or 0.0),
        "high": float(percentile(deltas, 0.975) or 0.0),
        "iterations": iterations,
    }


def _time_of_night_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hours = [float_value(row.get("local_hour")) for row in rows]
    clean = [hour for hour in hours if hour is not None]
    histogram: dict[str, int] = {}
    for hour in clean:
        bucket = f"{int(hour):02d}:00"
        histogram[bucket] = histogram.get(bucket, 0) + 1
    return {
        "n": len(clean),
        "median_local_hour": median(clean) if clean else None,
        "min_local_hour": min(clean) if clean else None,
        "max_local_hour": max(clean) if clean else None,
        "histogram": dict(sorted(histogram.items())),
    }


def _time_of_night_warning(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> str | None:
    baseline = _time_of_night_summary(baseline_rows)
    candidate = _time_of_night_summary(candidate_rows)
    if not baseline["n"] or not candidate["n"]:
        return None
    baseline_median = float(baseline["median_local_hour"])
    candidate_median = float(candidate["median_local_hour"])
    if abs(baseline_median - candidate_median) >= 2:
        return "baseline and candidate local-hour distributions differ materially"
    baseline_hours = set(baseline["histogram"])
    candidate_hours = set(candidate["histogram"])
    if baseline_hours and candidate_hours and not baseline_hours & candidate_hours:
        return "baseline and candidate have no overlapping local-hour buckets"
    return None


def _compatibility_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in COMPATIBILITY_FIELDS)


def _missing_compatibility_fields(row: dict[str, Any]) -> list[str]:
    return [field for field in COMPATIBILITY_FIELDS if row.get(field) in (None, "")]


def _compatibility_exclusion(
    row: dict[str, Any],
    *,
    reference_key: tuple[Any, ...] | None,
) -> list[str]:
    reasons: list[str] = []
    if row.get("comparison_eligible") is False:
        reasons.append("run_not_comparison_eligible")
    reasons.extend(f"{field}_missing" for field in _missing_compatibility_fields(row))
    if not reasons and reference_key is not None:
        for field, expected, actual in zip(
            COMPATIBILITY_FIELDS,
            reference_key,
            _compatibility_key(row),
            strict=True,
        ):
            if actual != expected:
                reasons.append(f"{field}_mismatch")
    return reasons


def compatible_comparison_rows(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    all_rows = [("baseline", row) for row in baseline_rows] + [
        ("candidate", row) for row in candidate_rows
    ]
    complete_keys = {
        _compatibility_key(row)
        for _cohort, row in all_rows
        if not _missing_compatibility_fields(row) and row.get("comparison_eligible") is not False
    }
    reference_key = next(iter(complete_keys)) if len(complete_keys) == 1 else None
    included: dict[str, list[dict[str, Any]]] = {"baseline": [], "candidate": []}
    excluded: list[dict[str, Any]] = []
    exclusion_counts: dict[str, int] = {}
    for cohort, row in all_rows:
        reasons = _compatibility_exclusion(row, reference_key=reference_key)
        if len(complete_keys) > 1 and not reasons:
            reasons = ["cohort_metadata_incompatible"]
        if reasons:
            excluded.append(
                {
                    "cohort": cohort,
                    "run_id": row.get("run_id"),
                    "reasons": reasons,
                }
            )
            for reason in reasons:
                exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        included[cohort].append(row)
    return {
        "baseline_rows": included["baseline"],
        "candidate_rows": included["candidate"],
        "excluded": excluded,
        "excluded_count": len(excluded),
        "exclusion_counts": exclusion_counts,
        "compatibility_key": dict(zip(COMPATIBILITY_FIELDS, reference_key, strict=True))
        if reference_key is not None
        else None,
        "compatible": len(complete_keys) == 1 and not excluded,
    }


def compare_cohorts(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    metric_name: str,
    path_id: str,
    min_runs: int = 5,
) -> dict[str, Any]:
    compatibility = compatible_comparison_rows(baseline_rows, candidate_rows)
    baseline_rows = compatibility["baseline_rows"]
    candidate_rows = compatibility["candidate_rows"]
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
    time_of_night = {
        "baseline": _time_of_night_summary(baseline_rows),
        "candidate": _time_of_night_summary(candidate_rows),
        "warning": _time_of_night_warning(baseline_rows, candidate_rows),
    }
    conclusion: dict[str, Any] = {
        "status": "INCONCLUSIVE",
        "reason": "minimum sample count was not met",
    }
    if not baseline_rows or not candidate_rows:
        conclusion = {"status": "NO_DATA", "reason": "one or both cohorts are empty"}
    if compatibility["excluded_count"]:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "one or more runs were excluded by compatibility checks",
        }
    elif not compatibility["compatible"]:
        conclusion = {
            "status": "INCONCLUSIVE",
            "reason": "baseline and candidate metadata are not compatible",
        }
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
        confidence_interval = _bootstrap_median_delta_ci(baseline_values, candidate_values)
        improvement_ci_clears_zero = False
        regression_ci_clears_zero = False
        if confidence_interval is not None:
            if policy["higher_is_better"]:
                improvement_ci_clears_zero = float(confidence_interval["low"]) > 0
                regression_ci_clears_zero = float(confidence_interval["high"]) < 0
            else:
                improvement_ci_clears_zero = float(confidence_interval["high"]) < 0
                regression_ci_clears_zero = float(confidence_interval["low"]) > 0
        if beneficial_delta >= threshold and improvement_ci_clears_zero:
            conclusion = {
                "status": "LIKELY_IMPROVEMENT",
                "reason": "median delta exceeds the practical threshold and CI excludes zero",
            }
        elif beneficial_delta <= -threshold and regression_ci_clears_zero:
            conclusion = {
                "status": "LIKELY_REGRESSION",
                "reason": (
                    "median delta exceeds the practical threshold in the negative direction "
                    "and CI excludes zero"
                ),
            }
        elif abs(beneficial_delta) >= threshold:
            conclusion = {
                "status": "INCONCLUSIVE",
                "reason": (
                    "median delta exceeds the practical threshold but bootstrap CI crosses zero"
                ),
            }
        else:
            conclusion = {
                "status": "INCONCLUSIVE",
                "reason": "median delta is below the practical threshold",
            }
        conclusion["delta"] = delta
        conclusion["relative_delta"] = relative_delta
        conclusion["practical_threshold"] = threshold
        conclusion["bootstrap_95_ci"] = confidence_interval
        if time_of_night["warning"] and conclusion["status"] != "INCONCLUSIVE":
            conclusion = {
                **conclusion,
                "status": "INCONCLUSIVE",
                "reason": str(time_of_night["warning"]),
                "uncontrolled_status": conclusion["status"],
            }
    return {
        "metric": metric_name,
        "path_id": path_id,
        "min_runs": min_runs,
        "protocol_hashes": hashes,
        "baseline": baseline,
        "candidate": candidate,
        "policy": policy,
        "conclusion": conclusion,
        "time_of_night": time_of_night,
        "compatibility": compatibility,
        "excluded_run_count": compatibility["excluded_count"],
        "exclusion_counts": compatibility["exclusion_counts"],
        "baseline_run_ids": [row.get("run_id") for row in baseline_rows],
        "candidate_run_ids": [row.get("run_id") for row in candidate_rows],
    }


def evaluate_run_integrity(
    run: TestRun,
    *,
    has_live_results: bool,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    comparable_protocol_ids = {"comparable-benchmark", "comparable-v1"}
    protocol_id = str(protocol.get("protocol_id") or "")
    protocol_hash_value = protocol.get("protocol_hash") or run.protocol_hash
    checks = {
        "protocol_hash_verified": bool(protocol_hash_value),
        "protocol_is_comparable": protocol_id in comparable_protocol_ids,
        "environment_snapshot_complete": bool(
            (run.integrity_json or {}).get("environment_snapshot_complete")
        ),
        "application_version_verified": bool(run.application_version),
        "test_node_version_verified": bool(run.test_node_version),
        "traffic_receiver_confirmed": bool(has_live_results),
        "latency_sample_count": len(
            [sample for sample in run.metric_samples if sample.metric_name.startswith("latency_")]
        ),
        "radio_sample_count": len(
            [sample for sample in run.metric_samples if sample.metric_name.startswith("radio_")]
        ),
    }
    checks["receiver_measurements_present"] = bool(has_live_results)
    exclusion_reasons = [
        reason
        for reason, ok in [
            ("protocol_hash_missing", checks["protocol_hash_verified"]),
            ("exploratory_or_legacy_protocol", checks["protocol_is_comparable"]),
            ("environment_snapshot_incomplete", checks["environment_snapshot_complete"]),
            ("application_version_missing", checks["application_version_verified"]),
            ("test_node_version_missing", checks["test_node_version_verified"]),
            ("traffic_not_receiver_confirmed", checks["receiver_measurements_present"]),
        ]
        if not ok
    ]
    comparison_eligible = not exclusion_reasons
    return {
        "comparison_eligible": comparison_eligible,
        "checks": checks,
        "exclusion_reasons": exclusion_reasons,
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
                    float_value(row.get("paths", {}).get(path_id, {}).get("video_success_percent"))
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
