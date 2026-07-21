from __future__ import annotations

import hashlib
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import BenchmarkProtocol, ProtocolStatus
from ltap_testbench.profiles.protocols import canonical_json

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


FROZEN_PROTOCOLS = {
    "comparable-v1": ("Comparable Benchmark v1", COMPARABLE_V1),
    "video-stability-v1": ("Video Stability v1", VIDEO_STABILITY_V1),
}


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
        digest = hashlib.sha256(canonical_json(definition).encode()).hexdigest()
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
            existing.definition_json = definition
            existing.protocol_hash = digest
            existing.result_schema_version = int(definition["result_schema_version"])
            existing.version = str(definition["version"])
    session.commit()
