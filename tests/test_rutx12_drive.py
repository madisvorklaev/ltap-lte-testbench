from __future__ import annotations

import json
import sys
from importlib import util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ltap_testbench.drive_tests import rutx12

WORKER_PATH = Path(__file__).resolve().parents[1] / "tools" / "rutx12_drive_worker.py"
SPEC = util.spec_from_file_location("rutx12_drive_worker", WORKER_PATH)
assert SPEC is not None and SPEC.loader is not None
worker = util.module_from_spec(SPEC)
sys.modules["rutx12_drive_worker"] = worker
SPEC.loader.exec_module(worker)


def test_selected_modem_uses_primary_flag_not_array_order() -> None:
    selected = rutx12.selected_modem(
        [
            {"id": "3-1", "primary": "0", "data_connected": "0"},
            {"id": "2-1", "primary": "1", "data_connected": "1"},
        ]
    )
    assert selected is not None
    assert selected["id"] == "2-1"


def test_modem_normalizer_keeps_absent_values_null_and_pseudonymous() -> None:
    row = rutx12.normalize_modem_status(
        {
            "imei": "123456789012345",
            "iccid": "8937200000000000000",
            "status": "registered",
            "packet_data": "yes",
            "address": "",
            "cell_info": [{"cell_id": "abc"}],
            "ca_signal": [{"band": "B3"}],
            "rsrp": "-91 dBm",
        },
        "rut-a",
        "2026-09-06T00:00:00+00:00",
    )
    assert row["registered"] is True
    assert row["data_connected"] is True
    assert row["selected_mobile_ipv4_present"] is False
    assert row["modem_id"].startswith("modem-")
    assert "123456789012345" not in json.dumps(row)
    assert row["cell_info"] == [{"cell_id": "abc"}]
    assert row["ca_signal"] == [{"band": "B3"}]
    assert row["rsrp_dbm"] == -91.0


def test_gps_rejects_zero_zero_and_out_of_range() -> None:
    zero = rutx12.normalize_gps({"valid": "yes", "lat": 0, "lon": 0})
    bad = rutx12.normalize_gps({"valid": "yes", "lat": 91, "lon": 24})
    assert zero["valid"] is False
    assert zero["latitude"] is None
    assert zero["invalid_reason"] == "ZERO_ZERO_COORDINATE"
    assert bad["valid"] is False
    assert bad["invalid_reason"] == "COORDINATE_OUT_OF_RANGE"


def test_ping_o_accounting_fills_explicit_and_sequence_gaps() -> None:
    result = rutx12.account_ping(
        [
            "[1] 64 bytes from 217.18.95.142: icmp_seq=10 ttl=55 time=45.1 ms",
            "[2] no answer yet for icmp_seq=11",
            "[3] 64 bytes from 217.18.95.142: icmp_seq=13 ttl=55 time=50.0 ms",
        ]
    )
    assert result["scheduled"] == 4
    assert result["answered"] == 2
    assert result["timed_out"] == 2
    assert result["loss_percent"] == 50.0


def test_iperf_requires_receiver_summary_and_preserves_zero_delivery() -> None:
    missing = rutx12.parse_iperf_json_text(
        json.dumps({"end": {"sum_sent": {"bits_per_second": 5_000_000}}})
    )
    zero = rutx12.parse_iperf_json_text(
        json.dumps(
            {
                "end": {
                    "sum_sent": {"bits_per_second": 5_000_000},
                    "sum_received": {
                        "sender": False,
                        "bits_per_second": 0,
                        "lost_packets": 100,
                        "packets": 100,
                        "lost_percent": 100.0,
                        "jitter_ms": 0.0,
                    },
                }
            }
        )
    )
    assert missing["valid"] is False
    assert missing["receiver_mbps"] is None
    assert missing["sender_mbps"] == 5.0
    assert zero["valid"] is True
    assert zero["receiver_mbps"] == 0.0
    assert zero["loss_percent"] == 100.0


def test_required_iperf_argv_is_integer_rate_single_stream() -> None:
    argv = rutx12.build_iperf_argv("217.18.95.142", 5201, "192.168.101.201")
    assert rutx12.validate_iperf_argv(argv) == []
    assert "-P" not in argv
    assert argv[argv.index("-b") + 1] == "5000000"
    assert argv[argv.index("-l") + 1] == "1200"


def test_epoch_classification_skew_cross_egress_and_partial() -> None:
    valid = {"classification": "VALID_DELIVERY"}
    unknown = {"classification": "UNATTRIBUTED_DELIVERY_UNMEASURED"}
    assert rutx12.classify_epoch(valid, valid, skew_s=0.2) == "VALID_DELIVERY"
    assert rutx12.classify_epoch(valid, valid, skew_s=2.1) == "INFRASTRUCTURE_INVALID"
    assert rutx12.classify_epoch(valid, valid, cross_egress=True) == "INFRASTRUCTURE_INVALID"
    assert rutx12.classify_epoch(valid, unknown) == "UNATTRIBUTED_DELIVERY_UNMEASURED"
    assert rutx12.classify_epoch(valid, valid, partial=True) == "PARTIAL_STOPPED_BY_USER"


def test_counter_reset_produces_null_delta_event_reason() -> None:
    assert rutx12.counter_delta(100, 150) == (50, None)
    assert rutx12.counter_delta(150, 100) == (None, "COUNTER_RESET")
    assert rutx12.counter_delta(None, 100) == (None, "MISSING_COUNTER")


def test_recompute_overnight_from_raw_evidence() -> None:
    run_dir = (
        Path(__file__).resolve().parents[1]
        / "runtime"
        / "rutx12-rb4011"
        / "20260905T195803Z-overnight-auto-dual5m-soak"
    )
    summary = rutx12.recompute_overnight_soak(run_dir)
    assert summary["scheduled_full_epochs"] == 93
    assert summary["right_censored_epochs"] == 1
    assert summary["paired_valid_epochs"] == 79
    assert summary["path_a"]["valid_epochs"] == 86
    assert summary["path_b"]["valid_epochs"] == 86
    assert summary["path_a"]["lost_packets"] == 5
    assert summary["path_b"]["lost_packets"] == 361247
    assert round(summary["path_a"]["loss_percent"], 7) == 0.0000372
    assert round(summary["path_b"]["loss_percent"], 5) == 2.68838
    assert summary["both_paths_good_epochs"] == 35


def test_real_rut_payload_bundle_uses_separate_address_route_and_boot_endpoints() -> None:
    bundle = {
        "/api/system/device/status": {
            "ok": True,
            "body": {"boot_id": "boot-redacted", "uptime": 456},
        },
        "/api/modems/status": {
            "ok": True,
            "body": {
                "data": [
                    {"id": "3-1", "primary": "0"},
                    {"id": "2-1", "primary": "1", "operator": "Telia"},
                ]
            },
        },
        "/api/modems/status/2-1": {
            "ok": True,
            "body": {
                "id": "2-1",
                "registered": "registered",
                "data_connected": "1",
                "rat": "LTE",
                "cell_info": [{"pci": 123, "earfcn": 1300}],
                "ca_signal": [{"band": "B20"}],
            },
        },
        "/api/modems/signal/status/2-1": {
            "ok": True,
            "body": {"rsrp": "-91 dBm", "rsrq": "-8 dB", "sinr": "13 dB"},
        },
        "/api/interfaces/status": {
            "ok": True,
            "body": {"data": [{"id": "mob1s1a1", "proto": "mobile", "ipv4": "10.10.10.2"}]},
        },
        "/api/network/devices/status": {
            "ok": True,
            "body": {"data": [{"id": "wwan0", "up": "1"}]},
        },
        "/api/ip_routes/ipv4/status": {
            "ok": True,
            "body": {"data": [{"target": "0.0.0.0/0", "interface": "mob1s1a1"}]},
        },
    }
    normalized = rutx12.normalize_api_bundle(bundle, "rut-a")
    assert normalized["boot_id"] == "boot-redacted"
    assert normalized["uptime_s"] == 456.0
    assert normalized["selected_mobile_ipv4_present"] is True
    assert normalized["default_route_present"] is True
    assert normalized["registered"] is True
    assert normalized["rsrp_dbm"] == -91.0


def test_ssh_ubus_payload_normalizes_mobile_child_interface_and_cache_state() -> None:
    bundle = {
        "/api/system/device/status": {
            "ok": True,
            "backend": "ssh",
            "body": {"boot_id": "boot-redacted", "uptime": 78089},
        },
        "/api/modems/status": {
            "ok": True,
            "backend": "ssh",
            "body": {"data": [{"id": "3-1", "primary": True, "data_connected": True}]},
        },
        "/api/modems/status/3-1": {
            "ok": True,
            "backend": "ssh",
            "body": {
                "id": "3-1",
                "primary": True,
                "cache": {
                    "operator": "Telia",
                    "reg_stat": 1,
                    "net_mode_str": "LTE",
                    "band_str": "LTE B7",
                    "rsrp_value": -99,
                    "rsrq_value": -15,
                    "sinr_value": 15,
                },
                "cell_info": [{"pcid": 156, "earfcn": 3050}],
                "ca_info": [],
                "pdp_addr": [{"addr": "10.52.176.1"}],
            },
        },
        "/api/interfaces/status": {
            "ok": True,
            "backend": "ssh",
            "body": {
                "interface": [
                    {
                        "interface": "mob1s1a1_4",
                        "proto": "dhcp",
                        "l3_device": "qmimux0",
                        "ipv4-address": [{"address": "10.52.176.1", "mask": 32}],
                        "route": [{"target": "0.0.0.0", "mask": 0}],
                        "data": {"modem": "3-1"},
                    }
                ]
            },
        },
        "/api/ip_routes/ipv4/status": {
            "ok": True,
            "backend": "ssh",
            "body": {
                "interface": [
                    {
                        "interface": "mob1s1a1_4",
                        "route": [{"target": "0.0.0.0", "mask": 0}],
                    }
                ]
            },
        },
    }
    normalized = rutx12.normalize_api_bundle(bundle, "rut-a")
    assert normalized["registered"] is True
    assert normalized["data_connected"] is True
    assert normalized["selected_mobile_ipv4_present"] is True
    assert normalized["default_route_present"] is True
    assert normalized["primary_band"] == "LTE B7"
    assert normalized["rsrp_dbm"] == -99.0


def test_receiver_evidence_rejects_missing_loss_and_short_output() -> None:
    argv = rutx12.build_iperf_argv(rutx12.SERVER_IPV4, 5201, rutx12.SOURCE_A)
    missing_loss = json.dumps(
        {
            "end": {
                "sum_sent": {"bits_per_second": 5_000_000},
                "sum_received": {
                    "sender": False,
                    "bits_per_second": 4_900_000,
                    "packets": 4000,
                    "jitter_ms": 3.0,
                },
            }
        }
    )
    short = rutx12.validate_receiver_evidence(argv, 0, 2.0, missing_loss)
    assert short["valid"] is False
    assert short["loss_percent"] is None
    assert "iperf duration shorter than required 10-second window" in short["problems"]


def test_checksum_lifecycle_detects_post_hash_mutation(tmp_path: Path) -> None:
    (tmp_path / "STATE.json").write_text('{"state":"READY_FOR_ROAD"}\n', encoding="utf-8")
    rutx12.write_checksums(tmp_path)
    assert rutx12.verify_checksums(tmp_path) == []
    (tmp_path / "STATE.json").write_text('{"state":"MUTATED"}\n', encoding="utf-8")
    assert rutx12.verify_checksums(tmp_path)


def test_verify_rejects_zero_evidence_false_pass(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "sid"
    public = tmp_path / "public" / "sid"
    runtime.mkdir(parents=True)
    public.mkdir(parents=True)
    worker.write_json(runtime / "STATE.json", {"state": "READY_FOR_ROAD"})
    worker.write_json(public / "summary.json", {"gate_passed": True, "attempted_dual_epochs": 0})
    rutx12.write_checksums(runtime)
    rutx12.write_checksums(public)
    problems = worker.verify_session(runtime, public)
    assert "zero measured epochs cannot pass" in problems
    assert "zero measured epochs cannot verify successfully" in problems


def test_cli_short_fake_gate_blocks_and_preserves_partial(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(worker, "ROOT", tmp_path / "runtime")
    monkeypatch.setattr(worker, "PUBLIC_ROOT", tmp_path / "public")
    monkeypatch.setattr(worker, "ACTIVE", tmp_path / "runtime" / "ACTIVE_SESSION.json")
    monkeypatch.setattr(worker, "LOCK", tmp_path / "runtime" / "ACTIVE_SESSION.lock")
    monkeypatch.setenv("RUTX12_FAKE_COMMANDS", "1")
    args = type(
        "Args",
        (),
        {"name": "pytest-gate", "idle_seconds": 0, "load_seconds": 11, "post_seconds": 0},
    )()
    rc = worker.validate_cmd(args)
    assert rc == 2
    sessions = list((tmp_path / "runtime").glob("rutx12-drive-*pytest-gate"))
    assert len(sessions) == 1
    summary = worker.read_json(tmp_path / "public" / sessions[0].name / "summary.json", {})
    assert summary["gate_passed"] is False
    assert summary["ready_line"] == (
        "READY FOR RUTX12 MOVING TEST: NO - FULL_15_MIN_STATIONARY_GATE_NOT_YET_RUN"
    )
    assert summary["attempted_dual_epochs"] >= 1
    assert summary["orphaned_processes"] == []
    assert worker.verify_session(sessions[0], tmp_path / "public" / sessions[0].name) == []


def test_road_start_requires_passed_gate_and_authorization(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(worker, "ROOT", tmp_path / "runtime")
    monkeypatch.setattr(worker, "PUBLIC_ROOT", tmp_path / "public")
    sid = "gate"
    runtime = tmp_path / "runtime" / sid
    public = tmp_path / "public" / sid
    runtime.mkdir(parents=True)
    public.mkdir(parents=True)
    worker.write_json(runtime / "STATE.json", {"state": "BLOCKED_STATIONARY_GATE"})
    worker.write_json(public / "summary.json", {"gate_passed": False})
    args = type(
        "Args",
        (),
        {
            "gate_session_id": sid,
            "departure_authorized_by": "Madis",
            "name": "road",
            "route_id": "route",
            "direction": "CW",
        },
    )()
    try:
        worker.start_cmd(args)
    except SystemExit as exc:
        assert "stationary gate has not passed" in str(exc)
    else:
        raise AssertionError("road start bypassed a failed stationary gate")


def test_indoor_gps_no_fix_is_not_stationary_gate_blocker(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "sid"
    public = tmp_path / "public" / "sid"
    runtime.mkdir(parents=True)
    public.mkdir(parents=True)
    worker.write_json(runtime / "STATE.json", {"state": "ANALYZING"})
    for path in ("rut-a", "rut-b"):
        for idx in range(20):
            rutx12.append_jsonl(
                runtime / path / "modem.jsonl",
                {
                    "utc": f"2026-09-06T00:00:{idx:02d}+00:00",
                    "boot_id": "boot",
                    "registered": True,
                    "data_connected": True,
                    "selected_mobile_ipv4_present": True,
                    "default_route_present": True,
                },
            )
    for idx in range(20):
        rutx12.append_jsonl(runtime / "gps" / "position.jsonl", {"valid": False, "seq": idx})
    for idx in range(10):
        rutx12.append_jsonl(
            runtime / "traffic" / "joint-epochs.jsonl",
            {"epoch_id": idx, "joint_classification": "VALID_DELIVERY"},
        )
        for path in ("path-a", "path-b"):
            rutx12.append_jsonl(
                runtime / "traffic" / "epoch-ledger.jsonl",
                {"epoch_id": idx, "path": path, "classification": "VALID_DELIVERY"},
            )
    rutx12.append_jsonl(
        runtime / "traffic" / "epoch-ledger.jsonl",
        {"epoch_id": "partial", "path": "path-a", "partial": True},
    )
    summary = worker.analyze_session(runtime, public, [])
    assert summary["gate_passed"] is True
    assert summary["gps_required_for_stationary_gate"] is False
    assert summary["gps_limitation"] == "GPS_UNAVAILABLE_OR_NO_FIX"
