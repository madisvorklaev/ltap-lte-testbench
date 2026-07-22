import json
import sys

import pytest

from ltap_testbench.traffic.commands import run_command
from ltap_testbench.traffic.http_upload import parse_curl_write_out
from ltap_testbench.traffic.iperf import build_iperf3_client_command, parse_iperf3_json
from ltap_testbench.traffic.irtt import build_irtt_client_command, parse_irtt_json
from ltap_testbench.traffic.tcp_upload import run_timed_tcp_upload
from ltap_testbench.traffic.udp_upload import run_udp_upload
from ltap_testbench.traffic.video_udp import run_video_udp_probe


def test_build_iperf3_command() -> None:
    command = build_iperf3_client_command(
        server="198.51.100.10",
        port=5002,
        duration_seconds=30,
        parallel_streams=4,
        udp=True,
        bitrate="5M",
    )
    assert command == [
        "iperf3",
        "--client",
        "198.51.100.10",
        "--port",
        "5002",
        "--time",
        "30",
        "--parallel",
        "4",
        "--json",
        "--udp",
        "--bitrate",
        "5M",
    ]


def test_parse_iperf3_json() -> None:
    summary = parse_iperf3_json(
        json.dumps(
            {
                "end": {
                    "sum_sent": {
                        "seconds": 30.0,
                        "bytes": 12_000_000,
                        "bits_per_second": 3_200_000.0,
                        "retransmits": 2,
                    }
                }
            }
        )
    )
    assert summary.bits_per_second == 3_200_000.0
    assert summary.retransmits == 2


def test_build_irtt_command() -> None:
    assert build_irtt_client_command("198.51.100.10", 5003, 60, 100) == [
        "irtt",
        "client",
        "198.51.100.10:5003",
        "--duration",
        "60s",
        "--interval",
        "100ms",
        "--fill=rand",
        "--json",
    ]


def test_parse_irtt_json() -> None:
    summary = parse_irtt_json(
        json.dumps(
            {
                "round_trips": {"sent": 100, "received": 98},
                "stats": {"rtt": {"median": 20_000_000, "p95": 80_000_000, "p99": 120_000_000}},
            }
        )
    )
    assert summary.loss_percent == 2
    assert summary.rtt_median_ms == 20
    assert summary.rtt_p95_ms == 80


def test_parse_curl_write_out() -> None:
    summary = parse_curl_write_out(
        json.dumps(
            {
                "http_code": "201",
                "time_connect": "0.123",
                "time_total": "10.0",
                "speed_upload": "1250000",
                "size_upload": "12500000",
                "remote_ip": "203.0.113.10",
                "remote_port": "18080",
            }
        )
    )
    assert summary.http_code == "201"
    assert summary.time_connect_seconds == 0.123
    assert summary.speed_upload_mbit_s == 10
    assert summary.remote_port == 18080


def test_run_command_can_cancel_subprocess() -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=30,
        should_cancel=lambda: True,
    )

    assert result.exit_code == 130
    assert "cancelled" in result.stderr


def test_run_udp_upload(monkeypatch) -> None:
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.address = address

        def send(self, payload):
            sent.append(payload)
            return len(payload)

    times = iter([0.0, 0.0, 0.01, 0.02, 0.03, 1.01, 1.01])
    monkeypatch.setattr("ltap_testbench.traffic.udp_upload.time.monotonic", lambda: next(times))
    monkeypatch.setattr("ltap_testbench.traffic.udp_upload.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "ltap_testbench.traffic.udp_upload.socket.socket", lambda *_args: FakeSocket()
    )

    result = run_udp_upload("198.51.100.10", 18080, 1, 1.0, 1000, run_id="run-a", token="t")

    assert result.target_port == 18080
    assert result.bytes_sent == len(sent) * 1000
    assert result.average_mbit_s > 0
    assert b'"token":"t"' in sent[0]


def test_run_timed_tcp_upload(monkeypatch) -> None:
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def settimeout(self, timeout):
            self.timeout = timeout

        def sendall(self, payload):
            sent.append(payload)

        def shutdown(self, _how):
            return None

        def recv(self, _size):
            return b"HTTP/1.1 202 Accepted\r\n\r\n"

    times = iter([0.0, 0.0, 0.2, 0.4, 1.1, 1.1])
    monkeypatch.setattr("ltap_testbench.traffic.tcp_upload.time.monotonic", lambda: next(times))
    monkeypatch.setattr(
        "ltap_testbench.traffic.tcp_upload.socket.create_connection",
        lambda *_args, **_kwargs: FakeSocket(),
    )

    result = run_timed_tcp_upload("198.51.100.10", 18080, "/upload/run-test", 1, token="t")

    assert result.target_port == 18080
    assert result.bytes_sent == 3 * 64 * 1024
    assert result.average_mbit_s > 0
    assert result.response_head.startswith("HTTP/1.1 202")
    assert sent[0].startswith(b"PUT /upload/run-test HTTP/1.1")
    assert b"X-Ltap-Token: t" in sent[0]


def test_run_video_udp_probe(monkeypatch) -> None:
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.address = address

        def send(self, payload):
            sent.append(payload)
            return len(payload)

    now = 0.0

    def monotonic() -> float:
        nonlocal now
        now += 0.02
        return now

    monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.monotonic", monotonic)
    monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.time_ns", lambda: 123)
    monkeypatch.setattr(
        "ltap_testbench.traffic.video_udp.socket.socket", lambda *_args: FakeSocket()
    )

    result = run_video_udp_probe(
        "198.51.100.10",
        18080,
        "run-video",
        "lte1",
        duration_seconds=1,
        bitrate_mbit_s=0.1,
        fps=25,
        resolution="1080p",
        scenario="city",
        token="t",
    )

    assert result.target_port == 18080
    assert result.frames_sent > 0
    assert result.datagrams_sent == len(sent)
    assert sent[0].startswith(b"LTAPFRAME ")
    assert b'"token":"t"' in sent[0]


def test_run_video_udp_probe_matches_requested_datagram_bitrate(monkeypatch) -> None:
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            self.address = address

        def send(self, payload):
            return len(payload)

    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    monkeypatch.setattr(
        "ltap_testbench.traffic.video_udp.socket.socket", lambda *_args: FakeSocket()
    )
    monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.time_ns", lambda: 123)

    for bitrate_mbit_s in [0.1, 0.5, 1, 5, 10, 50]:
        clock = FakeClock()
        monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.monotonic", clock.monotonic)
        monkeypatch.setattr("ltap_testbench.traffic.video_udp.time.sleep", clock.sleep)

        result = run_video_udp_probe(
            "198.51.100.10",
            18080,
            f"run-video-{bitrate_mbit_s}",
            "lte1",
            duration_seconds=1,
            bitrate_mbit_s=bitrate_mbit_s,
            fps=25,
            resolution="1080p",
            scenario="city",
        )

        assert result.frames_sent == 25
        assert result.average_mbit_s == pytest.approx(bitrate_mbit_s, rel=0.05)
