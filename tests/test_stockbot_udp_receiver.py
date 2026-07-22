import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load_stockbot_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "deploy" / "stockbot-fileserver.py"
    spec = importlib.util.spec_from_file_location("stockbot_fileserver_udp_tests", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_udp_receiver_builds_one_second_buckets(monkeypatch) -> None:
    stockbot = load_stockbot_module()
    stockbot.RUNS.clear()
    now_ns = iter(
        [
            1_000_000_000,
            1_500_000_000,
            2_200_000_000,
            2_300_000_000,
        ]
    )
    monkeypatch.setattr(stockbot.time, "time_ns", lambda: next(now_ns))

    stockbot.record_udp_datagram("run-udp", "src", 8088, 100, sequence=1, token_present=True)
    stockbot.record_udp_datagram("run-udp", "src", 8088, 100, sequence=2, token_present=True)
    stockbot.record_udp_datagram("run-udp", "src", 8088, 100, sequence=2, token_present=True)
    stockbot.record_udp_datagram("run-udp", "src", 8088, 100, sequence=0, token_present=True)

    record = stockbot.public_run_records("run-udp")[0]

    assert record["bytes_received"] == 400
    assert record["datagrams_received"] == 4
    assert record["unique_datagrams"] == 3
    assert record["duplicates"] == 1
    assert record["out_of_order"] == 1
    assert record["packet_loss_percent"] == 0
    assert record["token_present"] is True
    assert record["intervals"] == [
        {
            "offset_seconds": 0,
            "bytes": 200,
            "datagrams_received": 2,
            "unique_datagrams": 2,
            "duplicates": 0,
            "out_of_order": 0,
            "delivered_mbit_s": record["intervals"][0]["delivered_mbit_s"],
        },
        {
            "offset_seconds": 1,
            "bytes": 200,
            "datagrams_received": 2,
            "unique_datagrams": 1,
            "duplicates": 1,
            "out_of_order": 1,
            "delivered_mbit_s": record["intervals"][1]["delivered_mbit_s"],
        },
    ]
    assert all("_start_epoch_ns" not in bucket for bucket in record["intervals"])


def test_udp_receiver_reports_missing_sequence_loss(monkeypatch) -> None:
    stockbot = load_stockbot_module()
    stockbot.RUNS.clear()
    now_ns = iter([1_000_000_000, 2_000_000_000])
    monkeypatch.setattr(stockbot.time, "time_ns", lambda: next(now_ns))

    stockbot.record_udp_datagram("run-loss", "src", 8088, 100, sequence=1)
    stockbot.record_udp_datagram("run-loss", "src", 8088, 100, sequence=3)

    record = stockbot.public_run_records("run-loss")[0]

    assert record["missing_datagrams"] == 1
    assert record["packet_loss_percent"] == pytest.approx(100 / 3)
