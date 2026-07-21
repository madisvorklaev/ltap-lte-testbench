import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass


@dataclass(frozen=True)
class TcpTimedUploadResult:
    target_host: str
    target_port: int
    path: str
    requested_duration_seconds: int
    duration_seconds: float
    bytes_sent: int
    average_mbit_s: float
    response_head: str


def run_timed_tcp_upload(
    host: str,
    port: int,
    path: str,
    duration_seconds: int,
    chunk_bytes: int = 64 * 1024,
    should_cancel: Callable[[], bool] | None = None,
) -> TcpTimedUploadResult:
    payload = b"\0" * chunk_bytes
    request_head = (
        f"PUT {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "User-Agent: ltap-testbench-timed-uploader\r\n"
        "Content-Type: application/octet-stream\r\n"
        "Content-Length: 999999999999\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode()
    start = time.monotonic()
    deadline = start + duration_seconds
    bytes_sent = 0
    response_head = b""
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(max(duration_seconds + 30, 30))
        sock.sendall(request_head)
        while time.monotonic() < deadline and not (should_cancel and should_cancel()):
            try:
                sock.sendall(payload)
            except (BrokenPipeError, ConnectionResetError):
                break
            bytes_sent += len(payload)
        with suppress(OSError):
            sock.shutdown(socket.SHUT_WR)
        try:
            response_head = sock.recv(4096)
        except TimeoutError:
            response_head = b""
    elapsed = max(time.monotonic() - start, 0.001)
    return TcpTimedUploadResult(
        target_host=host,
        target_port=port,
        path=path,
        requested_duration_seconds=duration_seconds,
        duration_seconds=elapsed,
        bytes_sent=bytes_sent,
        average_mbit_s=bytes_sent * 8 / elapsed / 1_000_000,
        response_head=response_head.decode("utf-8", errors="replace"),
    )
