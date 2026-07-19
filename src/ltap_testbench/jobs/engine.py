from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import RouterProfile, RunEvent, RunState, TestPlan, TestRun
from ltap_testbench.routers.factory import adapter_for
from ltap_testbench.telemetry.controller import common_preflight

TERMINAL_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
    RunState.INTERRUPTED,
    RunState.RECOVERY_REQUIRED,
}


def add_event(
    session: Session,
    run: TestRun,
    event_type: str,
    message: str,
    details: dict | None = None,
) -> None:
    run.events.append(RunEvent(event_type=event_type, message=message, details=details or {}))
    run.updated_at = utc_now()
    session.add(run)
    session.commit()


def transition(session: Session, run: TestRun, state: RunState, reason: str | None = None) -> None:
    run.state = state
    run.state_reason = reason
    run.updated_at = utc_now()
    session.add(run)
    session.commit()
    add_event(session, run, "state", f"State changed to {state}", {"reason": reason})


def create_run(session: Session, router_slug: str, plan_slug: str) -> TestRun:
    router = session.scalar(select(RouterProfile).where(RouterProfile.slug == router_slug))
    if router is None:
        raise ValueError(f"Unknown router profile: {router_slug}")
    plan = session.scalar(select(TestPlan).where(TestPlan.slug == plan_slug))
    if plan is None:
        raise ValueError(f"Unknown test plan: {plan_slug}")
    run = TestRun(
        run_id=f"run-{uuid4().hex[:12]}",
        router_id=router.id,
        plan_slug=plan.slug,
        resolved_plan=plan.definition,
    )
    session.add(run)
    session.commit()
    add_event(session, run, "created", "Run created.", {"router": router.slug, "plan": plan.slug})
    return run


def execute_run(session: Session, run: TestRun) -> TestRun:
    router = run.router
    adapter = adapter_for(router)
    try:
        transition(session, run, RunState.PREFLIGHT)
        controller_check = common_preflight(router.controller_interface)
        add_event(
            session,
            run,
            "controller-preflight",
            "Controller preflight collected.",
            controller_check.to_dict(),
        )

        router_checks = adapter.preflight()
        for check in router_checks:
            add_event(session, run, "router-preflight", check.message, asdict(check))
        if any(not check.ok for check in router_checks):
            transition(session, run, RunState.FAILED, "router preflight failed")
            return run

        transition(session, run, RunState.VERIFYING_PATHS)
        path_checks = adapter.verify_paths()
        for check in path_checks:
            add_event(session, run, "path-verification", check.message, asdict(check))
        if any(not check.ok for check in path_checks):
            transition(session, run, RunState.FAILED, "path verification failed")
            return run

        transition(session, run, RunState.RUNNING)
        add_event(
            session,
            run,
            "simulated-measurement",
            "MVP simulated measurement completed; live traffic stages are not enabled yet.",
            {"latency_ms_median": 42.0, "latency_ms_p95": 88.0, "loss_percent": 0.0},
        )
        transition(session, run, RunState.ANALYZING)
        run.summary = {
            "validity": "simulated",
            "warnings": controller_check.warnings,
            "message": "MVP run completed using adapter checks and simulated measurements.",
        }
        session.add(run)
        session.commit()
        transition(session, run, RunState.COMPLETED)
    except Exception as exc:
        add_event(session, run, "error", str(exc), {"type": type(exc).__name__})
        transition(session, run, RunState.FAILED, str(exc))
    return run
