import hashlib
import json
from copy import deepcopy
from typing import Any

RESULT_SCHEMA_VERSION = 2
MEASUREMENT_IMPLEMENTATION_VERSION = "ltap-measurement-v2"
DEFAULT_PROTOCOL_ID = "exploratory-lab"
DEFAULT_PROTOCOL_VERSION = "1"
COMPARABLE_PROTOCOL_ID = "comparable-benchmark"
COMPARABLE_PROTOCOL_VERSION = "1"


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_protocol_definition(plan: dict[str, Any]) -> dict[str, Any]:
    plan_copy = deepcopy(plan)
    metadata_value = plan_copy.get("metadata")
    metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
    protocol_value = metadata.get("protocol")
    protocol_meta: dict[str, Any] = protocol_value if isinstance(protocol_value, dict) else {}
    return {
        "protocol_id": plan_copy.get("protocol_id")
        or protocol_meta.get("protocol_id")
        or DEFAULT_PROTOCOL_ID,
        "protocol_version": plan_copy.get("protocol_version")
        or protocol_meta.get("protocol_version")
        or str(plan_copy.get("version") or DEFAULT_PROTOCOL_VERSION),
        "stages": plan_copy.get("stages") or [],
        "latency": plan_copy.get("latency") or {},
        "tcp_upload": plan_copy.get("tcp_upload") or {},
        "udp_upload": plan_copy.get("udp_upload") or {},
        "video_probe": {
            key: value
            for key, value in (plan_copy.get("video_probe") or {}).items()
            if key != "resolution"
        },
        "traffic": plan_copy.get("traffic") or {},
        "telemetry": plan_copy.get("telemetry") or {},
        "measurement_implementation_version": MEASUREMENT_IMPLEMENTATION_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
    }


def protocol_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(canonical_protocol_definition(plan)).encode()).hexdigest()


def protocol_metadata(plan: dict[str, Any]) -> dict[str, Any]:
    definition = canonical_protocol_definition(plan)
    return {
        "protocol_id": definition["protocol_id"],
        "protocol_version": definition["protocol_version"],
        "protocol_hash": protocol_hash(plan),
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "measurement_implementation_version": MEASUREMENT_IMPLEMENTATION_VERSION,
        "canonical_definition": definition,
    }


def estimated_duration_seconds(plan: dict[str, Any]) -> int:
    stages = set(plan.get("stages") or [])
    total = 0
    latency = plan.get("latency") or {}
    tcp = plan.get("tcp_upload") or {}
    udp = plan.get("udp_upload") or {}
    video = plan.get("video_probe") or {}
    if "idle-latency" in stages:
        total += int(latency.get("duration_seconds") or 0)
    tcp_rounds = int(tcp.get("count") or 1) if "tcp-upload" in stages else 0
    tcp_seconds = int(tcp.get("duration_seconds") or 0)
    udp_seconds = int(udp.get("duration_seconds") or 0) if "udp-upload" in stages else 0
    udp_pattern = str(udp.get("pattern") or "end")
    total += tcp_rounds * tcp_seconds
    if udp_pattern == "after_each_tcp":
        total += tcp_rounds * udp_seconds
    elif "udp-upload" in stages:
        total += udp_seconds
    if video.get("enabled", True) and "video-udp-probe" in stages:
        total += int(video.get("duration_seconds") or 0)
        total += int(video.get("receiver_settle_seconds") or 0)
    return total
