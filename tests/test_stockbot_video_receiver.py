import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def load_stockbot_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "deploy" / "stockbot-fileserver.py"
    spec = importlib.util.spec_from_file_location("stockbot_fileserver_for_tests", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def frame_header(
    path_id: str,
    frame_id: int,
    fragment: int,
    fragments: int,
    send_ns: int,
) -> dict[str, object]:
    return {
        "run_id": "run-video",
        "token": "tok-video",
        "path_id": path_id,
        "frame_id": frame_id,
        "fragment_index": fragment,
        "fragment_count": fragments,
        "send_ns": send_ns,
    }


def reserve_video_run(stockbot: ModuleType) -> None:
    stockbot.RESERVATIONS.clear()
    stockbot.RESERVATIONS["res-video"] = {
        "id": "res-video",
        "owner": "pytest",
        "run_id": "run-video",
        "created_epoch": stockbot.time.time(),
        "ttl_seconds": 60,
        "token": "tok-video",
    }


def test_video_receiver_corrects_sender_skew_and_ignores_duplicates(monkeypatch: Any) -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    reserve_video_run(stockbot)
    arrivals = iter([1_000_000_000, 1_005_000_000, 2_000_000_000])
    monkeypatch.setattr(stockbot.time, "monotonic_ns", lambda: next(arrivals))

    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)
    stockbot.record_video_frame_datagram(frame_header("lte2", 1, 0, 1, 105_000_000), "b", 2, 1200)
    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)

    summary = stockbot.summarize_video_frames("run-video", finalize=True)

    assert summary["first_arrival_ties"] == 1
    assert summary["first_arrival_winners"] == {}
    assert summary["path_arrival_delta_ms_p95"] == 5
    assert summary["corrected_path_arrival_delta_ms_p95"] == 0
    assert summary["paths"]["lte1"]["frames_seen"] == 1
    assert summary["dual_path"]["complete_frame_ids_by_path"] == {"lte1": [1], "lte2": [1]}


def test_video_receiver_rejects_invalid_fragment_index() -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    reserve_video_run(stockbot)

    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 2, 2, 100_000_000), "a", 1, 1200)

    assert stockbot.summarize_video_frames("run-video")["paths"] == {}


def test_video_live_summary_does_not_finalize_partial_frame(monkeypatch: Any) -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    reserve_video_run(stockbot)
    arrivals = iter([1_000_000_000, 1_010_000_000])
    monkeypatch.setattr(stockbot.time, "monotonic_ns", lambda: next(arrivals))

    stockbot.record_video_frame_datagram(frame_header("lte1", 7, 0, 2, 100_000_000), "a", 1, 1200)
    live = stockbot.summarize_video_frames("run-video")
    stockbot.record_video_frame_datagram(frame_header("lte1", 7, 1, 2, 100_000_000), "a", 1, 1200)
    final = stockbot.summarize_video_frames("run-video", finalize=True, delete=True)

    assert live["summary_mode"] == "live"
    assert live["paths"]["lte1"]["frames_partial"] == 1
    assert live["paired_frames_complete"] is None
    assert final["paths"]["lte1"]["frames_complete"] == 1
    assert stockbot.summarize_video_frames("run-video")["paths"] == {}


def test_video_live_summary_skips_heavy_percentiles(monkeypatch: Any) -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    reserve_video_run(stockbot)
    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)

    def fail_percentile(_values: list[float], _pct: float) -> float:
        raise AssertionError("live summary should not calculate full-history percentiles")

    monkeypatch.setattr(stockbot, "percentile", fail_percentile)

    live = stockbot.summarize_video_frames("run-video")

    assert live["summary_mode"] == "live"
    assert live["paths"]["lte1"]["frames_seen"] == 1


def test_video_receiver_rejects_missing_reservation_token() -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    stockbot.RESERVATIONS.clear()

    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)

    assert stockbot.summarize_video_frames("run-video")["paths"] == {}
