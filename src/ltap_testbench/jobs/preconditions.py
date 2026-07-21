from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ltap_testbench.routers.base import RouterAdapter

REGISTERED_STATUSES = {"registered", "connected"}


@dataclass(frozen=True)
class StabilityResult:
    ok: bool
    outcome_code: str
    message: str
    required_seconds: int
    observed_stable_seconds: float
    samples: list[dict]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "outcome_code": self.outcome_code,
            "message": self.message,
            "required_seconds": self.required_seconds,
            "observed_stable_seconds": self.observed_stable_seconds,
            "samples": self.samples,
        }


def _paths_registered(samples: list[dict]) -> bool:
    if not samples:
        return False
    for sample in samples:
        status = str(sample.get("status") or "").lower()
        if status not in REGISTERED_STATUSES:
            return False
    return True


def wait_for_stable_paths(
    adapter: RouterAdapter,
    *,
    required_seconds: int,
    timeout_seconds: int,
    poll_interval_seconds: int,
    cancel_check: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> StabilityResult:
    required_seconds = max(0, required_seconds)
    timeout_seconds = max(1, timeout_seconds)
    poll_interval_seconds = max(1, poll_interval_seconds)
    deadline = monotonic() + timeout_seconds
    stable_since: float | None = None
    observed = 0.0
    samples: list[dict] = []
    while True:
        if cancel_check():
            return StabilityResult(
                ok=False,
                outcome_code="USER_CANCELLED",
                message="Cancelled while waiting for stable LTE paths.",
                required_seconds=required_seconds,
                observed_stable_seconds=observed,
                samples=samples,
            )
        now = monotonic()
        if now >= deadline:
            return StabilityResult(
                ok=False,
                outcome_code="MODEM_NOT_REGISTERED",
                message="LTE paths did not remain registered for the required window.",
                required_seconds=required_seconds,
                observed_stable_seconds=observed,
                samples=samples,
            )
        telemetry = adapter.collect_path_telemetry()
        sample = {
            "offset_seconds": round(timeout_seconds - (deadline - now), 3),
            "paths": telemetry,
            "all_registered": _paths_registered(telemetry),
        }
        samples.append(sample)
        if sample["all_registered"]:
            stable_since = stable_since if stable_since is not None else now
            observed = now - stable_since
            if observed >= required_seconds:
                return StabilityResult(
                    ok=True,
                    outcome_code="OK",
                    message="LTE paths remained registered for the required window.",
                    required_seconds=required_seconds,
                    observed_stable_seconds=observed,
                    samples=samples,
                )
        else:
            stable_since = None
            observed = 0.0
        sleep(min(poll_interval_seconds, max(0.0, deadline - now)))
