from ltap_testbench.db.models import RunState

TERMINAL_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
    RunState.INTERRUPTED,
    RunState.RECOVERY_REQUIRED,
}

RESTORATION_STATES = {
    RunState.PREPARING_ROUTER,
    RunState.VERIFYING_PATHS,
    RunState.WARMING_UP,
    RunState.RUNNING,
    RunState.COOLING_DOWN,
    RunState.CANCEL_REQUESTED,
}

ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.QUEUED, RunState.PREFLIGHT, RunState.CANCELLED},
    RunState.QUEUED: {RunState.PREFLIGHT, RunState.CANCEL_REQUESTED},
    RunState.PREFLIGHT: {
        RunState.AWAITING_CONFIRMATION,
        RunState.VERIFYING_PATHS,
        RunState.CANCEL_REQUESTED,
        RunState.FAILED,
    },
    RunState.AWAITING_CONFIRMATION: {
        RunState.PREPARING_ROUTER,
        RunState.VERIFYING_PATHS,
        RunState.CANCEL_REQUESTED,
        RunState.CANCELLED,
    },
    RunState.PREPARING_ROUTER: {
        RunState.VERIFYING_PATHS,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.VERIFYING_PATHS: {
        RunState.WARMING_UP,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.WARMING_UP: {
        RunState.RUNNING,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.RUNNING: {
        RunState.COOLING_DOWN,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.COOLING_DOWN: {
        RunState.ANALYZING,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.ANALYZING: {
        RunState.GENERATING_REPORT,
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.FAILED,
    },
    RunState.GENERATING_REPORT: {
        RunState.CANCEL_REQUESTED,
        RunState.RESTORING,
        RunState.COMPLETED,
        RunState.FAILED,
    },
    RunState.RESTORING: {
        RunState.COMPLETED,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.RECOVERY_REQUIRED,
    },
    RunState.CANCEL_REQUESTED: {RunState.RESTORING, RunState.CANCELLED, RunState.RECOVERY_REQUIRED},
    RunState.CANCELLED: set(),
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.INTERRUPTED: {RunState.RESTORING, RunState.RECOVERY_REQUIRED},
    RunState.RECOVERY_REQUIRED: set(),
}


def require_transition(current: RunState, target: RunState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid run transition: {current} -> {target}")


def restart_target_for(state: RunState) -> RunState | None:
    if state in TERMINAL_STATES:
        return None
    if state in RESTORATION_STATES:
        return RunState.RESTORING
    return RunState.INTERRUPTED
