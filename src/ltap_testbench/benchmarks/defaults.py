from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.benchmarks.protocols import protocol_hash
from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import BenchmarkProtocol, ProtocolStatus, TestProfile

COMPARABLE_V1: dict[str, Any] = {
    "id": "comparable-v1",
    "version": "1",
    "result_schema_version": 2,
    "path_concurrency": "parallel",
    "stabilization": {
        "timeout_seconds": 300,
        "required_registered_seconds": 120,
        "poll_interval_seconds": 5,
    },
    "latency_sampler": {
        "interval_seconds": 1,
        "enabled_during": ["idle", "tcp", "recovery", "udp", "video", "final_recovery"],
    },
    "radio_sampler": {"interval_seconds": 5},
    "idle_baseline": {"duration_seconds": 60},
    "tcp": {
        "mode": "timed",
        "stream_count": 1,
        "warmup_seconds": 10,
        "measured_seconds": 60,
        "rounds": 3,
        "recovery_seconds_between_rounds": 30,
        "receiver_bucket_seconds": 1,
    },
    "udp": {
        "duration_seconds": 120,
        "bitrate_mbit_s": 5.0,
        "datagram_bytes": 1200,
        "sequence_header_version": 1,
        "receiver_bucket_seconds": 1,
    },
    "post_udp_recovery": {"duration_seconds": 30},
    "video": {
        "duration_seconds": 300,
        "bitrate_mbit_s": 5.0,
        "fps": 25,
        "payload_bytes": 1200,
        "trace_id": "synthetic-city-v1",
        "trace_version": 1,
        "trace_seed": 1001,
        "receiver_bucket_seconds": 1,
        "receiver_settle_seconds": 5,
    },
    "final_recovery": {"duration_seconds": 60},
    "batch": {"default_inter_run_cooldown_seconds": 120},
}


VIDEO_STABILITY_V1: dict[str, Any] = {
    "id": "video-stability-v1",
    "version": "1",
    "result_schema_version": 2,
    "stabilization": {
        "timeout_seconds": 300,
        "required_registered_seconds": 120,
        "poll_interval_seconds": 5,
    },
    "idle_baseline": {"duration_seconds": 60},
    "latency_sampler": {"interval_seconds": 1},
    "radio_sampler": {"interval_seconds": 5},
    "video": {
        "duration_seconds": 3600,
        "bitrate_mbit_s": 5.0,
        "fps": 25,
        "payload_bytes": 1200,
        "trace_id": "synthetic-city-v1",
        "trace_version": 1,
        "trace_seed": 1001,
        "receiver_bucket_seconds": 1,
        "receiver_settle_seconds": 5,
    },
    "final_recovery": {"duration_seconds": 60},
}


VIDEO_CITY_5MBPS_25FPS_30M_V1: dict[str, Any] = {
    "id": "video-city-5mbps-25fps-30m-v1",
    "version": "1",
    "result_schema_version": 3,
    "comparable": True,
    "path_concurrency": "parallel",
    "stabilization": {
        "required_registered_seconds": 120,
        "timeout_seconds": 300,
        "poll_interval_seconds": 5,
    },
    "idle_baseline": {"duration_seconds": 60},
    "latency_sampler": {
        "interval_seconds": 1,
        "enabled_during": ["idle", "video", "final_recovery"],
    },
    "radio_sampler": {"interval_seconds": 5},
    "video": {
        "duration_seconds": 1800,
        "bitrate_mbit_s": 5.0,
        "fps": 25,
        "scenario": "city",
        "payload_bytes": 1200,
        "trace_id": "synthetic-city-v1",
        "trace_version": 1,
        "trace_seed": 1001,
        "receiver_bucket_seconds": 1,
        "receiver_settle_seconds": 5,
    },
    "final_recovery": {"duration_seconds": 60},
    "batch": {
        "default_inter_run_cooldown_seconds": 120,
        "default_max_consecutive_failures": 3,
        "default_attempt_multiplier": 1.25,
        "minimum_extra_attempts": 2,
    },
}


FROZEN_PROTOCOLS = {
    "comparable-v1": ("Comparable Benchmark v1", COMPARABLE_V1),
    "video-stability-v1": ("Video Stability v1", VIDEO_STABILITY_V1),
    "video-city-5mbps-25fps-30m-v1": (
        "Video Stability — City, 5 Mbps, 25 fps",
        VIDEO_CITY_5MBPS_25FPS_30M_V1,
    ),
}


PROFILE_SEEDS: list[dict[str, Any]] = [
    {
        "slug": "video-city-5mbps-25fps",
        "name": "Video Stability — City, 5 Mbps, 25 fps",
        "description": (
            "Repeated dual-LTE video tests using a fixed 5 Mbps, 25 fps city-driving "
            "traffic trace. Each valid run streams video for 30 minutes."
        ),
        "protocol_slug": "video-city-5mbps-25fps-30m-v1",
        "profile_version": "1",
        "is_comparable": True,
        "is_default": True,
        "display_order": 1,
        "default_target_mode": "streamed_time",
        "default_target_value": 6.0,
    },
    {
        "slug": "comparable-v1",
        "name": "Full Comparable Benchmark",
        "description": ("Complete throughput, loss, latency, radio, and video comparison."),
        "protocol_slug": "comparable-v1",
        "profile_version": "1",
        "is_comparable": True,
        "is_default": False,
        "display_order": 2,
        "default_target_mode": "valid_runs",
        "default_target_value": 5.0,
    },
    {
        "slug": "quick-connection-check",
        "name": "Quick Connection Check",
        "description": (
            "Diagnostic only — excluded from comparison analytics. Verifies router access, "
            "path registration, route selection, test-node access, and basic traffic flow."
        ),
        "protocol_slug": "video-city-5mbps-25fps-30m-v1",
        "profile_version": "1",
        "is_comparable": False,
        "is_default": False,
        "display_order": 3,
        "default_target_mode": "valid_runs",
        "default_target_value": 1.0,
    },
]


def protocol_duration_seconds(definition: dict[str, Any]) -> int:
    total = 0
    stabilization = definition.get("stabilization") or {}
    total += int(stabilization.get("required_registered_seconds") or 0)
    total += int((definition.get("idle_baseline") or {}).get("duration_seconds") or 0)
    tcp = definition.get("tcp") or {}
    if tcp:
        total += int(tcp.get("warmup_seconds") or 0)
        total += int(tcp.get("rounds") or 0) * int(tcp.get("measured_seconds") or 0)
        total += max(0, int(tcp.get("rounds") or 0) - 1) * int(
            tcp.get("recovery_seconds_between_rounds") or 0
        )
    total += int((definition.get("udp") or {}).get("duration_seconds") or 0)
    total += int((definition.get("post_udp_recovery") or {}).get("duration_seconds") or 0)
    video = definition.get("video") or {}
    total += int(video.get("duration_seconds") or 0)
    total += int(video.get("receiver_settle_seconds") or 0)
    total += int((definition.get("final_recovery") or {}).get("duration_seconds") or 0)
    return total


def seed_benchmark_protocols(session: Session) -> None:
    now = utc_now().astimezone(UTC)
    for slug, (name, definition) in FROZEN_PROTOCOLS.items():
        existing = session.scalar(select(BenchmarkProtocol).where(BenchmarkProtocol.slug == slug))
        digest = protocol_hash(definition)
        if existing is None:
            session.add(
                BenchmarkProtocol(
                    slug=slug,
                    version=str(definition["version"]),
                    name=name,
                    definition_json=definition,
                    protocol_hash=digest,
                    result_schema_version=int(definition["result_schema_version"]),
                    status=ProtocolStatus.FROZEN,
                    frozen_at=now,
                )
            )
            continue
        if existing.status == ProtocolStatus.FROZEN:
            stored_digest = protocol_hash(existing.definition_json)
            if existing.protocol_hash != stored_digest:
                raise RuntimeError(f"frozen benchmark protocol {slug} has an invalid stored hash")
            if existing.protocol_hash != digest:
                raise RuntimeError(
                    f"frozen benchmark protocol {slug} differs from the in-code definition; "
                    "create a new protocol version instead of mutating it"
                )
            continue
        existing.definition_json = definition
        existing.protocol_hash = digest
        existing.result_schema_version = int(definition["result_schema_version"])
        existing.version = str(definition["version"])
    session.flush()
    protocols_by_slug = {
        protocol.slug: protocol for protocol in session.scalars(select(BenchmarkProtocol)).all()
    }
    for seed in PROFILE_SEEDS:
        protocol = protocols_by_slug[seed["protocol_slug"]]
        profile = session.scalar(select(TestProfile).where(TestProfile.slug == seed["slug"]))
        if profile is None:
            profile = TestProfile(slug=seed["slug"], protocol_id=protocol.id)
        profile.name = seed["name"]
        profile.description = seed["description"]
        profile.protocol_id = protocol.id
        profile.protocol_hash = protocol.protocol_hash
        profile.profile_version = seed["profile_version"]
        profile.is_comparable = seed["is_comparable"]
        profile.is_default = seed["is_default"]
        profile.display_order = seed["display_order"]
        profile.default_target_mode = seed["default_target_mode"]
        profile.default_target_value = seed["default_target_value"]
        profile.default_inter_run_cooldown_seconds = int(
            protocol.definition_json.get("batch", {}).get(
                "default_inter_run_cooldown_seconds",
                120,
            )
        )
        profile.default_max_consecutive_failures = int(
            protocol.definition_json.get("batch", {}).get(
                "default_max_consecutive_failures",
                3,
            )
        )
        session.add(profile)
    session.commit()
