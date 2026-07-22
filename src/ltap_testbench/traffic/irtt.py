import json
from dataclasses import dataclass

from ltap_testbench.traffic.commands import CommandResult, run_command


@dataclass(frozen=True)
class IrttSummary:
    sent: int | None
    received: int | None
    loss_percent: float | None
    rtt_median_ms: float | None
    rtt_p95_ms: float | None
    rtt_p99_ms: float | None
    raw: dict


def build_irtt_client_command(
    server: str,
    port: int,
    duration_seconds: int,
    interval_ms: int = 100,
) -> list[str]:
    return [
        "irtt",
        "client",
        f"{server}:{port}",
        "--duration",
        f"{duration_seconds}s",
        "--interval",
        f"{interval_ms}ms",
        "--fill=rand",
        "--json",
    ]


def _duration_ns_to_ms(value: int | float | None) -> float | None:
    if value is None:
        return None
    return float(value) / 1_000_000


def parse_irtt_json(output: str) -> IrttSummary:
    data = json.loads(output)
    round_trips = data.get("round_trips", {})
    stats = data.get("stats", {})
    rtt = stats.get("rtt", {})
    sent = round_trips.get("sent")
    received = round_trips.get("received")
    loss_percent = None
    if sent:
        loss_percent = max(0, sent - (received or 0)) * 100 / sent
    return IrttSummary(
        sent=sent,
        received=received,
        loss_percent=loss_percent,
        rtt_median_ms=_duration_ns_to_ms(rtt.get("median")),
        rtt_p95_ms=_duration_ns_to_ms(rtt.get("p95")),
        rtt_p99_ms=_duration_ns_to_ms(rtt.get("p99")),
        raw=data,
    )


def run_irtt_client(
    server: str,
    port: int,
    duration_seconds: int,
    interval_ms: int = 100,
    timeout_seconds: float | None = None,
) -> tuple[CommandResult, IrttSummary | None]:
    command = build_irtt_client_command(
        server=server,
        port=port,
        duration_seconds=duration_seconds,
        interval_ms=interval_ms,
    )
    result = run_command(command, timeout_seconds=timeout_seconds)
    if result.exit_code != 0 or not result.stdout:
        return result, None
    return result, parse_irtt_json(result.stdout)
