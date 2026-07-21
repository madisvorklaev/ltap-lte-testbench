from collections.abc import Callable
from datetime import timedelta
from threading import Event

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ltap_testbench.benchmarks.defaults import seed_benchmark_protocols
from ltap_testbench.core.time import utc_now
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import (
    AntennaProfile,
    BatchAttempt,
    BatchAttemptState,
    BatchState,
    BenchmarkProtocol,
    GainSource,
    RunState,
)
from ltap_testbench.db.models import (
    TestBatch as DbTestBatch,
)
from ltap_testbench.db.models import (
    TestRun as DbTestRun,
)
from ltap_testbench.jobs.batch_runner import recover_interrupted_batches, run_batch
from ltap_testbench.profiles.defaults import seed_demo_data


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = session_factory()
    seed_demo_data(session)
    seed_benchmark_protocols(session)
    return session


def _antenna(session: Session) -> AntennaProfile:
    profile = AntennaProfile(
        slug="roof-panel",
        manufacturer="ACME",
        model="Panel",
        antenna_type="panel",
        gain_source=GainSource.MANUFACTURER,
        nominal_peak_gain_dbi=7.0,
        gain_by_band_json=[],
        cable_type="LMR",
        cable_length_m=1.0,
        estimated_cable_loss_db=1.0,
        mounting_location="roof",
        orientation="south",
    )
    session.add(profile)
    session.commit()
    return profile


def _batch(
    session: Session,
    *,
    target_valid_runs: int = 2,
    max_attempts: int = 3,
    cooldown: int = 0,
    deadline: timedelta | None = None,
) -> DbTestBatch:
    protocol = session.scalar(
        select(BenchmarkProtocol).where(BenchmarkProtocol.slug == "comparable-v1")
    )
    assert protocol is not None
    profile = _antenna(session)
    batch = DbTestBatch(
        batch_id="batch-test",
        name="Batch test",
        protocol_slug=protocol.slug,
        protocol_hash=protocol.protocol_hash,
        router_slug="demo-fake-ltap",
        antenna_profile_id=profile.id,
        target_valid_runs=target_valid_runs,
        max_attempts=max_attempts,
        inter_run_cooldown_seconds=cooldown,
        max_consecutive_failures=3,
        deadline=utc_now() + deadline if deadline else None,
    )
    session.add(batch)
    session.commit()
    return batch


def _executor(outcomes: list[bool]) -> Callable[[Session, DbTestRun, Event | None], DbTestRun]:
    remaining = iter(outcomes)

    def execute(session: Session, run: DbTestRun, _cancel_event: Event | None) -> DbTestRun:
        eligible = next(remaining)
        run.state = RunState.COMPLETED
        run.summary = {
            "comparison_eligible": eligible,
            "exclusion_reasons": [] if eligible else ["fixture_invalid"],
        }
        session.add(run)
        session.commit()
        return run

    return execute


def test_batch_stops_after_target_valid_runs_and_preserves_invalid_attempts() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=2, max_attempts=3)

    run_batch(session, batch, run_executor=_executor([True, False, True]))

    assert batch.state == BatchState.COMPLETED
    assert batch.state_reason == "target_reached"
    assert batch.attempt_count == 3
    assert batch.valid_run_count == 2
    assert batch.invalid_run_count == 1
    attempts = session.scalars(select(BatchAttempt).order_by(BatchAttempt.sequence_number)).all()
    assert [attempt.state for attempt in attempts] == [
        BatchAttemptState.VALID,
        BatchAttemptState.INVALID,
        BatchAttemptState.VALID,
    ]


def test_batch_fails_when_max_attempts_reached_before_valid_target() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=2, max_attempts=2)

    run_batch(session, batch, run_executor=_executor([False, False]))

    assert batch.state == BatchState.FAILED
    assert batch.state_reason == "max_attempts_reached"
    assert batch.attempt_count == 2
    assert batch.valid_run_count == 0
    assert batch.invalid_run_count == 2


def test_batch_deadline_stops_without_failure() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=2, max_attempts=3, deadline=timedelta(seconds=-1))

    run_batch(session, batch, run_executor=_executor([True, True]))

    assert batch.state == BatchState.COMPLETED
    assert batch.state_reason == "deadline_reached"
    assert batch.attempt_count == 0


def test_batch_cancel_during_cooldown_is_responsive() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=2, max_attempts=3, cooldown=10)
    cancel_event = Event()

    def sleep(_seconds: float) -> None:
        cancel_event.set()

    run_batch(
        session,
        batch,
        cancel_event=cancel_event,
        run_executor=_executor([True]),
        sleep=sleep,
    )

    assert batch.state == BatchState.CANCELLED
    assert batch.state_reason == "user_cancelled"
    assert batch.attempt_count == 1
    assert batch.valid_run_count == 1


def test_batch_runner_links_attempt_to_run() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=1, max_attempts=1)

    run_batch(session, batch, run_executor=_executor([True]))

    attempt = session.scalar(select(BatchAttempt))
    assert attempt is not None
    run = session.scalar(select(DbTestRun).where(DbTestRun.run_id == attempt.run_id))
    assert run is not None
    assert run.batch_id == batch.batch_id
    assert run.batch_attempt_id == attempt.id
    assert run.protocol_hash == batch.protocol_hash


def test_recover_interrupted_batch_marks_active_attempt_failed_and_pauses() -> None:
    session = _session()
    batch = _batch(session, target_valid_runs=2, max_attempts=3)
    batch.state = BatchState.RUNNING
    batch.attempt_count = 1
    session.add(batch)
    session.commit()
    run = DbTestRun(
        run_id="run-active",
        router_id=1,
        plan_slug="quick-check",
        state=RunState.RUNNING,
        batch_id=batch.batch_id,
    )
    session.add(run)
    session.commit()
    attempt = BatchAttempt(
        batch=batch,
        sequence_number=1,
        state=BatchAttemptState.RUNNING,
        run_id=run.run_id,
    )
    session.add(attempt)
    session.commit()

    recovered = recover_interrupted_batches(session)

    assert [item.batch_id for item in recovered] == [batch.batch_id]
    assert batch.state == BatchState.PAUSED
    assert batch.state_reason == "worker_restarted"
    assert batch.failed_attempt_count == 1
    assert batch.consecutive_failure_count == 1
    assert attempt.state == BatchAttemptState.FAILED
    assert attempt.outcome_code == "WORKER_RESTARTED"
    assert run.state == RunState.INTERRUPTED
