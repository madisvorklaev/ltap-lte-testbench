from collections.abc import Callable

from ltap_testbench.jobs.preconditions import wait_for_stable_paths


class SequenceAdapter:
    def __init__(self, samples: list[list[dict]]):
        self.samples = samples
        self.index = 0

    def collect_path_telemetry(self) -> list[dict]:
        if self.index >= len(self.samples):
            return self.samples[-1]
        sample = self.samples[self.index]
        self.index += 1
        return sample


def _clock() -> tuple[Callable[[], float], Callable[[float], None]]:
    state = {"now": 0.0}

    def monotonic() -> float:
        return state["now"]

    def sleep(seconds: float) -> None:
        state["now"] += seconds

    return monotonic, sleep


def test_wait_for_stable_paths_requires_continuous_registered_window() -> None:
    monotonic, sleep = _clock()
    adapter = SequenceAdapter(
        [
            [{"path_id": "lte1", "status": "registered"}],
            [{"path_id": "lte1", "status": "registered"}],
            [{"path_id": "lte1", "status": "registered"}],
        ]
    )

    result = wait_for_stable_paths(
        adapter,  # type: ignore[arg-type]
        required_seconds=2,
        timeout_seconds=5,
        poll_interval_seconds=1,
        cancel_check=lambda: False,
        sleep=sleep,
        monotonic=monotonic,
    )

    assert result.ok is True
    assert result.outcome_code == "OK"
    assert len(result.samples) == 3


def test_wait_for_stable_paths_times_out_when_path_not_registered() -> None:
    monotonic, sleep = _clock()
    adapter = SequenceAdapter([[{"path_id": "lte1", "status": "searching"}]])

    result = wait_for_stable_paths(
        adapter,  # type: ignore[arg-type]
        required_seconds=2,
        timeout_seconds=3,
        poll_interval_seconds=1,
        cancel_check=lambda: False,
        sleep=sleep,
        monotonic=monotonic,
    )

    assert result.ok is False
    assert result.outcome_code == "MODEM_NOT_REGISTERED"
    assert result.observed_stable_seconds == 0


def test_wait_for_stable_paths_can_be_cancelled() -> None:
    monotonic, sleep = _clock()
    adapter = SequenceAdapter([[{"path_id": "lte1", "status": "registered"}]])

    result = wait_for_stable_paths(
        adapter,  # type: ignore[arg-type]
        required_seconds=2,
        timeout_seconds=5,
        poll_interval_seconds=1,
        cancel_check=lambda: True,
        sleep=sleep,
        monotonic=monotonic,
    )

    assert result.ok is False
    assert result.outcome_code == "USER_CANCELLED"
    assert result.samples == []
