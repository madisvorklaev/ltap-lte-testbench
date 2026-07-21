from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.models import MetricSample, RouterProfile, TestRun
from ltap_testbench.routers.factory import adapter_for


def _float_from_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


@dataclass
class PhaseContext:
    phase: str = "setup"
    phase_instance: str | None = None


class RunMetricSampler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        run_id: str,
        *,
        target_host: str | None,
        latency_interval_seconds: float = 1.0,
        radio_interval_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._session_factory = session_factory
        self._run_id = run_id
        self._target_host = target_host
        self._latency_interval_seconds = max(0.1, latency_interval_seconds)
        self._radio_interval_seconds = max(0.1, radio_interval_seconds)
        self._sleep = sleep
        self._stop = threading.Event()
        self._phase = PhaseContext()
        self._phase_lock = threading.Lock()
        self._start_monotonic = time.monotonic()
        self._thread: threading.Thread | None = None

    def set_phase(self, phase: str, phase_instance: str | None = None) -> None:
        with self._phase_lock:
            self._phase = PhaseContext(phase=phase, phase_instance=phase_instance)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"metric-sampler-{self._run_id}")
        self._thread.daemon = True
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def sample_once(self) -> None:
        with self._session_factory() as session:
            run = session.query(TestRun).filter(TestRun.run_id == self._run_id).one_or_none()
            if run is None:
                return
            router = session.get(RouterProfile, run.router_id)
            if router is None:
                return
            adapter = adapter_for(router)
            samples = []
            if self._target_host:
                samples.extend(self._latency_samples(adapter, run))
            samples.extend(self._radio_samples(adapter, run))
            if samples:
                session.add_all(samples)
                session.commit()

    def _run(self) -> None:
        next_latency = 0.0
        next_radio = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if self._target_host and now >= next_latency:
                    self._write_latency()
                    next_latency = now + self._latency_interval_seconds
                if now >= next_radio:
                    self._write_radio()
                    next_radio = now + self._radio_interval_seconds
            except Exception:
                # Sampling must never fail the traffic run it observes.
                pass
            wait_for = min(next_latency if self._target_host else next_radio, next_radio) - now
            self._stop.wait(max(0.05, min(0.25, wait_for)))

    def _write_latency(self) -> None:
        with self._session_factory() as session:
            run = session.query(TestRun).filter(TestRun.run_id == self._run_id).one_or_none()
            if run is None:
                return
            router = session.get(RouterProfile, run.router_id)
            if router is None:
                return
            adapter = adapter_for(router)
            samples = self._latency_samples(adapter, run)
            if samples:
                session.add_all(samples)
                session.commit()

    def _write_radio(self) -> None:
        with self._session_factory() as session:
            run = session.query(TestRun).filter(TestRun.run_id == self._run_id).one_or_none()
            if run is None:
                return
            router = session.get(RouterProfile, run.router_id)
            if router is None:
                return
            adapter = adapter_for(router)
            samples = self._radio_samples(adapter, run)
            if samples:
                session.add_all(samples)
                session.commit()

    def _base_sample(
        self,
        run: TestRun,
        *,
        path_id: str | None,
        metric_name: str,
        value: float,
        unit: str,
        validity: str = "valid",
        details: dict[str, Any] | None = None,
    ) -> MetricSample:
        with self._phase_lock:
            phase = self._phase
        return MetricSample(
            run_pk=run.id,
            timestamp=utc_now(),
            offset_ms=int((time.monotonic() - self._start_monotonic) * 1000),
            path_id=path_id,
            phase=phase.phase,
            phase_instance=phase.phase_instance,
            metric_name=metric_name,
            value=value,
            unit=unit,
            validity=validity,
            details_json=details or {},
        )

    def _latency_samples(self, adapter: Any, run: TestRun) -> list[MetricSample]:
        if not self._target_host:
            return []
        rows = adapter.measure_latency(self._target_host, count=1)
        samples: list[MetricSample] = []
        for row in rows:
            path_id = str(row.get("path_id") or "") or None
            validity = str(row.get("validity") or "valid")
            avg_ms = _float_from_value(row.get("avg_ms"))
            loss_percent = _float_from_value(row.get("loss_percent"))
            received = _float_from_value(row.get("received"))
            if avg_ms is not None:
                samples.append(
                    self._base_sample(
                        run,
                        path_id=path_id,
                        metric_name="latency_rtt_ms",
                        value=avg_ms,
                        unit="ms",
                        validity=validity,
                        details=row,
                    )
                )
            if loss_percent is not None:
                samples.append(
                    self._base_sample(
                        run,
                        path_id=path_id,
                        metric_name="latency_loss_percent",
                        value=loss_percent,
                        unit="percent",
                        validity=validity,
                        details=row,
                    )
                )
            if received is not None:
                samples.append(
                    self._base_sample(
                        run,
                        path_id=path_id,
                        metric_name="latency_received",
                        value=received,
                        unit="count",
                        validity=validity,
                        details=row,
                    )
                )
        return samples

    def _radio_samples(self, adapter: Any, run: TestRun) -> list[MetricSample]:
        rows = adapter.collect_path_telemetry()
        samples: list[MetricSample] = []
        radio_fields = {
            "rsrp": ("radio_rsrp_dbm", "dBm"),
            "rsrq": ("radio_rsrq_db", "dB"),
            "sinr": ("radio_sinr_db", "dB"),
            "rssi": ("radio_rssi_dbm", "dBm"),
            "tx_mbit_s": ("router_tx_mbit_s", "Mbit/s"),
            "rx_mbit_s": ("router_rx_mbit_s", "Mbit/s"),
        }
        for row in rows:
            path_id = str(row.get("path_id") or "") or None
            samples.append(
                self._base_sample(
                    run,
                    path_id=path_id,
                    metric_name="radio_sample",
                    value=1.0,
                    unit="sample",
                    details=row,
                )
            )
            for source_key, (metric_name, unit) in radio_fields.items():
                value = _float_from_value(row.get(source_key))
                if value is None:
                    continue
                samples.append(
                    self._base_sample(
                        run,
                        path_id=path_id,
                        metric_name=metric_name,
                        value=value,
                        unit=unit,
                        details=row,
                    )
                )
        return samples
