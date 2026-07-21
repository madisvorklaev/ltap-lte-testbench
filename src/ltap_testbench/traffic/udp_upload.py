import socket
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class UdpUploadResult:
    target_host: str
    target_port: int
    duration_seconds: float
    requested_duration_seconds: int
    bitrate_mbit_s: float
    datagram_bytes: int
    datagrams_sent: int
    bytes_sent: int
    average_mbit_s: float


def run_udp_upload(
    host: str,
    port: int,
    duration_seconds: int,
    bitrate_mbit_s: float,
    datagram_bytes: int = 1200,
    run_id: str | None = None,
) -> UdpUploadResult:
    prefix = f"LTAPUDP {run_id}\n".encode() if run_id else b""
    if len(prefix) >= datagram_bytes:
        raise ValueError("run_id prefix is larger than the configured UDP datagram size")
    payload = prefix + (b"\0" * (datagram_bytes - len(prefix)))
    interval = datagram_bytes * 8 / (bitrate_mbit_s * 1_000_000)
    start = time.monotonic()
    deadline = start + duration_seconds
    next_send = start
    datagrams = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1)
        sock.connect((host, port))
        while time.monotonic() < deadline:
            sock.send(payload)
            datagrams += 1
            next_send += interval
            sleep_for = next_send - time.monotonic()
            while sleep_for > 0:
                time.sleep(min(sleep_for, 0.05))
                sleep_for = next_send - time.monotonic()
    elapsed = max(time.monotonic() - start, 0.001)
    bytes_sent = datagrams * datagram_bytes
    return UdpUploadResult(
        target_host=host,
        target_port=port,
        duration_seconds=elapsed,
        requested_duration_seconds=duration_seconds,
        bitrate_mbit_s=bitrate_mbit_s,
        datagram_bytes=datagram_bytes,
        datagrams_sent=datagrams,
        bytes_sent=bytes_sent,
        average_mbit_s=bytes_sent * 8 / elapsed / 1_000_000,
    )
