import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PUBLIC_COLLECTOR = REPO / "references/public-iperf-kit/ltap_public_test.py"
DRIVE_WORKER = REPO / "tools/elmo_lte_drive_worker.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_udp_summary_never_uses_sender_when_receiver_missing() -> None:
    collector = _load_module(PUBLIC_COLLECTOR, "ltap_public_test_regression")

    summary = collector.summarize_iperf(
        {
            "end": {
                "sum_sent": {
                    "bits_per_second": 5_000_000.0,
                    "lost_packets": 0,
                    "packets": 500,
                    "lost_percent": 0.0,
                }
            }
        },
        "udp",
        False,
    )

    assert summary["error"] == "missing receiver UDP summary"
    assert summary["receiver_summary_present"] is False
    assert summary["sender_mbps"] == 5.0
    assert summary.get("mbps") is None
    assert summary.get("lost_percent") is None


def test_public_udp_summary_rejects_ambiguous_sum_without_sum_received() -> None:
    collector = _load_module(PUBLIC_COLLECTOR, "ltap_public_test_regression_sum")

    summary = collector.summarize_iperf(
        {
            "end": {
                "sum": {
                    "bits_per_second": 5_000_000.0,
                    "lost_packets": 0,
                    "packets": 500,
                    "lost_percent": 0.0,
                }
            }
        },
        "udp",
        False,
    )

    assert summary["error"] == "missing receiver UDP summary"
    assert summary.get("mbps") is None


def test_drive_worker_udp_summary_keeps_receiver_metrics_null(tmp_path: Path) -> None:
    worker = _load_module(DRIVE_WORKER, "elmo_lte_drive_worker_regression")
    result = tmp_path / "iperf.json"
    result.write_text(
        json.dumps({"end": {"sum_sent": {"bits_per_second": 5_000_000.0}}}),
        encoding="utf-8",
    )

    summary = worker.parse_iperf_summary(result)

    assert summary["error"] == "missing receiver UDP summary"
    assert summary["sender_mbps"] == 5.0
    assert summary["receiver_mbps"] is None
    assert summary["loss_percent"] is None
