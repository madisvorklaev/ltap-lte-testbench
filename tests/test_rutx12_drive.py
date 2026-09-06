from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ltap_testbench.drive_tests import rutx12


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
