import json
from dataclasses import dataclass

from ltap_testbench.traffic.commands import CommandResult, run_command


@dataclass(frozen=True)
class IperfSummary:
    bits_per_second: float | None
    bytes_transferred: int | None
    seconds: float | None
    retransmits: int | None
    raw: dict


def build_iperf3_client_command(
    server: str,
    port: int,
    duration_seconds: int,
    parallel_streams: int = 1,
    udp: bool = False,
    bitrate: str | None = None,
) -> list[str]:
    command = [
        "iperf3",
        "--client",
        server,
        "--port",
        str(port),
        "--time",
        str(duration_seconds),
        "--parallel",
        str(parallel_streams),
        "--json",
    ]
    if udp:
        command.append("--udp")
    if bitrate:
        command.extend(["--bitrate", bitrate])
    return command


def parse_iperf3_json(output: str) -> IperfSummary:
    data = json.loads(output)
    end = data.get("end", {})
    summary = (
        end.get("sum_sent")
        or end.get("sum")
        or end.get("sum_received")
        or end.get("streams", [{}])[0].get("sender", {})
    )
    return IperfSummary(
        bits_per_second=summary.get("bits_per_second"),
        bytes_transferred=summary.get("bytes"),
        seconds=summary.get("seconds"),
        retransmits=summary.get("retransmits"),
        raw=data,
    )


def run_iperf3_client(
    server: str,
    port: int,
    duration_seconds: int,
    parallel_streams: int = 1,
    udp: bool = False,
    bitrate: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[CommandResult, IperfSummary | None]:
    command = build_iperf3_client_command(
        server=server,
        port=port,
        duration_seconds=duration_seconds,
        parallel_streams=parallel_streams,
        udp=udp,
        bitrate=bitrate,
    )
    result = run_command(command, timeout_seconds=timeout_seconds)
    if result.exit_code != 0 or not result.stdout:
        return result, None
    return result, parse_iperf3_json(result.stdout)
