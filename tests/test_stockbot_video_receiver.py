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
        "path_id": path_id,
        "frame_id": frame_id,
        "fragment_index": fragment,
        "fragment_count": fragments,
        "send_ns": send_ns,
    }


def test_video_receiver_corrects_sender_skew_and_ignores_duplicates(monkeypatch: Any) -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()
    arrivals = iter([1_000_000_000, 1_005_000_000, 2_000_000_000])
    monkeypatch.setattr(stockbot.time, "monotonic_ns", lambda: next(arrivals))

    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)
    stockbot.record_video_frame_datagram(frame_header("lte2", 1, 0, 1, 105_000_000), "b", 2, 1200)
    stockbot.record_video_frame_datagram(frame_header("lte1", 1, 0, 1, 100_000_000), "a", 1, 1200)

    summary = stockbot.summarize_video_frames("run-video")

    assert summary["first_arrival_ties"] == 1
    assert summary["first_arrival_winners"] == {}
    assert summary["path_arrival_delta_ms_p95"] == 5
    assert summary["corrected_path_arrival_delta_ms_p95"] == 0
    assert summary["paths"]["lte1"]["frames_seen"] == 1


def test_video_receiver_rejects_invalid_fragment_index() -> None:
    stockbot = load_stockbot_module()
    stockbot.VIDEO_FRAMES.clear()

    stockbot.record_video_frame_datagram(
        frame_header("lte1", 1, 2, 2, 100_000_000), "a", 1, 1200
    )

    assert stockbot.summarize_video_frames("run-video")["paths"] == {}
