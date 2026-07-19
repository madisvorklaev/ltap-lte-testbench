import json

from ltap_testbench.traffic.http_upload import parse_curl_write_out
from ltap_testbench.traffic.iperf import build_iperf3_client_command, parse_iperf3_json
from ltap_testbench.traffic.irtt import build_irtt_client_command, parse_irtt_json


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
                "time_total": "10.0",
                "speed_upload": "1250000",
                "size_upload": "12500000",
                "remote_ip": "203.0.113.10",
                "remote_port": "18080",
            }
        )
    )
    assert summary.http_code == "201"
    assert summary.speed_upload_mbit_s == 10
    assert summary.remote_port == 18080
