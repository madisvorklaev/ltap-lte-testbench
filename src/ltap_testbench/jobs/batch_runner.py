from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import (
    BatchAttempt,
    BatchAttemptState,
    BatchState,
    BenchmarkProtocol,
    RunState,
    TestBatch,
    TestPlan,
    TestRun,
)
from ltap_testbench.jobs.engine import create_run, execute_run
from ltap_testbench.profiles.schemas import TestPlanConfig

RunExecutor = Callable[[Session, TestRun, Event | None], TestRun]


def benchmark_plan_definition(protocol: BenchmarkProtocol, server_slug: str = "stockbot") -> dict:
    definition = protocol.definition_json
    tcp = definition.get("tcp") or {}
    udp = definition.get("udp") or {}
    video = definition.get("video") or {}
    latency = definition.get("idle_baseline") or {}
    stages = ["preflight", "path-verification", "idle-latency"]
    if tcp:
        stages.append("tcp-upload")
    if udp:
        stages.append("udp-upload")
    if video:
        stages.append("video-udp-probe")
    plan = {
        "slug": f"benchmark-{protocol.slug}",
        "name": protocol.name,
        "version": protocol.version,
        "protocol_id": protocol.slug,
        "protocol_version": protocol.version,
        "result_schema_version": protocol.result_schema_version,
        "server_slug": server_slug,
        "stages": stages,
        "latency": {
            "duration_seconds": int(latency.get("duration_seconds") or 60),
            "interval_ms": int(
                (definition.get("latency_sampler") or {}).get("interval_seconds") or 1
            )
            * 1000,
        },
        "tcp_upload": {
            "duration_seconds": int(tcp.get("measured_seconds") or 60),
            "count": int(tcp.get("rounds") or 1),
            "parallel_streams": [int(tcp.get("stream_count") or 1)],
            "payload_bytes": None if tcp.get("mode") == "timed" else tcp.get("payload_bytes"),
        },
        "udp_upload": {
            "duration_seconds": int(udp.get("duration_seconds") or 30),
            "bitrate_mbit_s": float(udp.get("bitrate_mbit_s") or 5.0),
            "datagram_bytes": int(udp.get("datagram_bytes") or 1200),
            "pattern": "end",
        },
        "video_probe": {
            "enabled": bool(video),
            "duration_seconds": int(video.get("duration_seconds") or 30),
            "bitrate_mbit_s": float(video.get("bitrate_mbit_s") or 5.0),
            "fps": int(video.get("fps") or 25),
            "payload_bytes": int(video.get("payload_bytes") or 1200),
            "receiver_settle_seconds": int(video.get("receiver_settle_seconds") or 5),
            "traffic_seed": str(video.get("trace_seed") or "1001"),
            "trace_id": str(video.get("trace_id") or "synthetic-city-v1"),
            "generator_version": f"trace-v{video.get('trace_version') or 1}",
        },
        "traffic": {"path_concurrency": definition.get("path_concurrency", "parallel")},
        "telemetry": definition.get("radio_sampler") or {},
        "metadata": {"protocol": {"protocol_hash": protocol.protocol_hash}},
    }
    return TestPlanConfig.model_validate(plan).model_dump(mode="json")


def ensure_batch_plan(session: Session, protocol: BenchmarkProtocol) -> TestPlan:
    slug = f"benchmark-{protocol.slug}"
    definition = benchmark_plan_definition(protocol)
    plan = session.scalar(select(TestPlan).where(TestPlan.slug == slug))
    if plan is None:
        plan = TestPlan(
            slug=slug,
            name=protocol.name,
            version=protocol.version,
            definition=definition,
        )
    else:
        plan.name = protocol.name
        plan.version = protocol.version
        plan.definition = definition
    session.add(plan)
    session.commit()
    return plan


def _finish_batch(session: Session, batch: TestBatch, state: BatchState, reason: str) -> None:
    batch.state = state
    batch.state_reason = reason
    if state in {BatchState.CANCELLED, BatchState.COMPLETED, BatchState.FAILED}:
        batch.completed_at = utc_now()
    session.add(batch)
    session.commit()


def _deadline_reached(batch: TestBatch) -> bool:
    if batch.deadline is None:
        return False
    now = utc_now()
    if batch.deadline.tzinfo is None:
        return now.replace(tzinfo=None) >= batch.deadline
    return now >= batch.deadline


def _finish_attempt(
    session: Session,
    batch: TestBatch,
    attempt: BatchAttempt,
    run: TestRun | None,
) -> None:
    attempt.finished_at = utc_now()
    if run is None:
        attempt.state = BatchAttemptState.FAILED
        attempt.outcome_code = "UNEXPECTED_ERROR"
        batch.failed_attempt_count += 1
        batch.consecutive_failure_count += 1
        return
    attempt.run_id = run.run_id
    attempt.comparison_eligible = bool((run.summary or {}).get("comparison_eligible"))
    if run.state == RunState.COMPLETED and attempt.comparison_eligible:
        attempt.state = BatchAttemptState.VALID
        attempt.outcome_code = "OK"
        batch.valid_run_count += 1
        batch.consecutive_failure_count = 0
    elif run.state == RunState.CANCELLED:
        attempt.state = BatchAttemptState.CANCELLED
        attempt.outcome_code = "USER_CANCELLED"
        batch.consecutive_failure_count += 1
    elif run.state == RunState.COMPLETED:
        attempt.state = BatchAttemptState.INVALID
        attempt.outcome_code = "INELIGIBLE_RUN"
        attempt.outcome_details_json = {
            "exclusion_reasons": (run.summary or {}).get("exclusion_reasons") or []
        }
        batch.invalid_run_count += 1
        batch.consecutive_failure_count = 0
    else:
        attempt.state = BatchAttemptState.FAILED
        attempt.outcome_code = str(run.state.value)
        batch.failed_attempt_count += 1
        batch.consecutive_failure_count += 1


def run_batch(
    session: Session,
    batch: TestBatch,
    *,
    cancel_event: Event | None = None,
    run_executor: RunExecutor | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TestBatch:
    if batch.state not in {BatchState.DRAFT, BatchState.SCHEDULED, BatchState.RUNNING}:
        return batch
    executor = run_executor or (lambda s, r, e: execute_run(s, r, cancel_event=e))
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.protocol_hash == batch.protocol_hash)
    )
    if protocol is None:
        _finish_batch(session, batch, BatchState.FAILED, "benchmark protocol not found")
        return batch
    plan = ensure_batch_plan(session, protocol)
    batch.state = BatchState.RUNNING
    batch.started_at = batch.started_at or utc_now()
    session.add(batch)
    session.commit()
    while True:
        session.refresh(batch)
        if batch.state == BatchState.CANCEL_REQUESTED or (
            cancel_event is not None and cancel_event.is_set()
        ):
            _finish_batch(session, batch, BatchState.CANCELLED, "user_cancelled")
            return batch
        if _deadline_reached(batch):
            _finish_batch(session, batch, BatchState.COMPLETED, "deadline_reached")
            return batch
        if batch.valid_run_count >= batch.target_valid_runs:
            _finish_batch(session, batch, BatchState.COMPLETED, "target_reached")
            return batch
        if batch.attempt_count >= batch.max_attempts:
            _finish_batch(session, batch, BatchState.FAILED, "max_attempts_reached")
            return batch
        if (
            batch.consecutive_failure_count >= batch.max_consecutive_failures
            and batch.consecutive_failure_count > 0
        ):
            _finish_batch(session, batch, BatchState.PAUSED, "max_consecutive_failures")
            return batch
        batch.attempt_count += 1
        attempt = BatchAttempt(
            batch=batch,
            sequence_number=batch.attempt_count,
            state=BatchAttemptState.RUNNING,
            started_at=utc_now(),
        )
        session.add_all([batch, attempt])
        session.commit()
        run = create_run(session, batch.router_slug, plan.slug)
        attempt.run_id = run.run_id
        session.add(attempt)
        session.commit()
        run = executor(session, run, cancel_event)
        _finish_attempt(session, batch, attempt, run)
        session.add_all([batch, attempt])
        session.commit()
        if batch.valid_run_count >= batch.target_valid_runs:
            _finish_batch(session, batch, BatchState.COMPLETED, "target_reached")
            return batch
        if batch.attempt_count >= batch.max_attempts:
            _finish_batch(session, batch, BatchState.FAILED, "max_attempts_reached")
            return batch
        if batch.inter_run_cooldown_seconds > 0:
            deadline = time.monotonic() + batch.inter_run_cooldown_seconds
            while time.monotonic() < deadline:
                session.refresh(batch)
                if batch.state == BatchState.CANCEL_REQUESTED or (
                    cancel_event is not None and cancel_event.is_set()
                ):
                    _finish_batch(session, batch, BatchState.CANCELLED, "user_cancelled")
                    return batch
                if _deadline_reached(batch):
                    _finish_batch(session, batch, BatchState.COMPLETED, "deadline_reached")
                    return batch
                sleep(min(0.25, deadline - time.monotonic()))
