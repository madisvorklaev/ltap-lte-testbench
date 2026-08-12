from __future__ import annotations

import csv
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import elmo_lte_drive_worker as worker

from ltap_testbench.drive_tests.v2 import (
    analyze_session,
    append_jsonl,
    build_timeline,
    detect_lte_events,
    diversity_summary,
    parse_lte_monitor,
    parse_routeros_gps,
    synthetic_verification,
)


def test_synthetic_verification_stage_a_passes() -> None:
    checks = synthetic_verification()
    assert checks
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_gps_parser_rejects_zero_zero() -> None:
    parsed = parse_routeros_gps("valid: yes\nlatitude: 0\nlongitude: 0\n")
    assert parsed["valid"] is False
    assert parsed["latitude"] is None
    assert parsed["longitude"] is None
    assert parsed["gps_valid_reason"] == "ZERO_ZERO_COORDINATE"


def test_gps_parser_accepts_routeros_nmea_compact_coordinates() -> None:
    parsed = parse_routeros_gps("valid: yes\nlatitude: 5922.0159\nlongitude: 02455.2192\nspeed: 7.2 km/h\n")
    assert parsed["valid"] is True
    assert round(parsed["latitude"], 6) == 59.366932
    assert round(parsed["longitude"], 6) == 24.92032
    assert parsed["speed_mps"] == 2.0


def test_lte_event_detection_transitions() -> None:
    rows = [
        parse_lte_monitor("status: registered\ncurrent-operator: Telia\nprimary-band: B3\ncell-id: A\n", "lte2", "2026-08-12T00:00:00+00:00"),
        parse_lte_monitor("status: registered\ncurrent-operator: Telia\nprimary-band: B20\ncell-id: A\n", "lte2", "2026-08-12T00:00:01+00:00"),
        parse_lte_monitor("status: registered\ncurrent-operator: Telia\nprimary-band: B20\ncell-id: B\n", "lte2", "2026-08-12T00:00:02+00:00"),
        parse_lte_monitor("status: searching\ncurrent-operator: Telia\nprimary-band: B20\ncell-id: B\n", "lte2", "2026-08-12T00:00:03+00:00"),
        parse_lte_monitor("status: registered\ncurrent-operator: Telia\nprimary-band: B20\ncell-id: B\n", "lte2", "2026-08-12T00:00:04+00:00"),
    ]
    types = [e["type"] for e in detect_lte_events(rows, "lte2")]
    assert "BAND_CHANGE" in types
    assert "CELL_CHANGE" in types
    assert "REGISTRATION_LOST" in types
    assert "REGISTRATION_RESTORED" in types


def test_timeline_stale_cutoff_and_single_band(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    public = tmp_path / "public"
    append_jsonl(runtime / "gps.jsonl", {"utc": "2026-08-12T00:00:00+00:00", "valid": True, "latitude": 59.1, "longitude": 24.1, "speed_mps": 0})
    for path, operator in (("lte1", "Elisa"), ("lte2", "Telia")):
        append_jsonl(
            runtime / f"{path}.jsonl",
            {
                "utc": "2026-08-12T00:00:00+00:00",
                "operator": operator,
                "primary_band": "B3",
                "cell_id": "A",
                "registered": True,
            },
        )
        append_jsonl(runtime / f"ping_{path}.jsonl", {"utc": "2026-08-12T00:00:00+00:00", "success": True, "rtt_ms": 30})
        append_jsonl(
            runtime / f"traffic_{path}.jsonl",
            {
                "interval_start_utc": "2026-08-12T00:00:00+00:00",
                "interval_end_utc": "2026-08-12T00:00:10+00:00",
                "receiver_mbps": 5.9,
                "loss_percent": 0,
                "udp_loss_window_s": 10,
            },
        )
    rows = build_timeline(runtime, public)
    assert rows[0]["lte1_band"] == "B3"
    assert ";" not in rows[0]["lte1_band"]
    assert rows[3]["lte1_band"] is None
    with (public / "timeline.csv").open(encoding="utf-8") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert csv_rows[0]["lte1_operator"] == "Elisa"


def test_analyze_legacy_labels_coarse_data(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "drive-old"
    public = tmp_path / "public" / "drive-old"
    runtime.mkdir(parents=True)
    public.mkdir(parents=True)
    (public / "timeline.csv").write_text("epoch,lte1\n1,B3;B20\n", encoding="utf-8")
    (public / "REPORT.md").write_text("Old report\n", encoding="utf-8")
    summary = analyze_session(runtime, public)
    assert summary["resolution"] == "LEGACY_COARSE_EPOCH_DATA"
    assert "LEGACY_COARSE_EPOCH_DATA" in (public / "REPORT.md").read_text(encoding="utf-8")


def test_diversity_categories() -> None:
    timeline = [
        {"lte1_registered": True, "lte2_registered": True, "lte1_ping_p95": 50, "lte2_ping_p95": 50, "lte1_ping_loss": 0, "lte2_ping_loss": 0},
        {"lte1_registered": True, "lte2_registered": True, "lte1_ping_p95": 150, "lte2_ping_p95": 50, "lte1_ping_loss": 0, "lte2_ping_loss": 0},
        {"lte1_registered": True, "lte2_registered": True, "lte1_ping_p95": 50, "lte2_ping_p95": 150, "lte1_ping_loss": 0, "lte2_ping_loss": 0},
        {"lte1_registered": True, "lte2_registered": True, "lte1_ping_p95": 150, "lte2_ping_p95": 150, "lte1_ping_loss": 0, "lte2_ping_loss": 0},
    ]
    summary = diversity_summary(timeline)
    assert summary["both_good"] == 1
    assert summary["elisa_impaired_telia_good"] == 1
    assert summary["telia_impaired_elisa_good"] == 1
    assert summary["both_impaired"] == 1


def test_traffic_epoch_marks_partial_when_stop_file_appears(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_iperf = fake_bin / "iperf3"
    fake_iperf.write_text(
        "#!/usr/bin/env python3\n"
        "import json, signal, sys, time\n"
        "def stop(*_):\n"
        "    print(json.dumps({'intervals': [{'sum': {'seconds': 1}}], 'end': {}}))\n"
        "    sys.stdout.flush()\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    fake_iperf.chmod(fake_iperf.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(worker, "campaign", lambda: {"server_ipv4": "127.0.0.1"})
    state = {"current_epoch": 1, "session_map": {"lte1": {"operator": "Elisa"}}}
    stop = threading.Event()
    thread = threading.Thread(
        target=worker.traffic_epoch,
        args=(tmp_path, state, "lte1", "127.0.0.1", 5201, 10, False, stop),
    )
    thread.start()
    time.sleep(0.5)
    (tmp_path / "STOP_REQUESTED").write_text("stop\n", encoding="utf-8")
    thread.join(timeout=5)
    assert not thread.is_alive()
    row = json.loads((tmp_path / "traffic_lte1.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["partial"] is True
    assert row["partial_reason"] == "PARTIAL_STOPPED_BY_USER"
