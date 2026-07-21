import json
import random
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

SCENARIO_BURST = {
    "parked": 0.35,
    "city": 0.75,
    "highway": 0.95,
    "rough-road": 1.25,
}


@dataclass(frozen=True)
class VideoUdpProbeResult:
    target_host: str
    target_port: int
    run_id: str
    path_id: str
    resolution: str
    scenario: str
    duration_seconds: float
    requested_duration_seconds: int
    bitrate_mbit_s: float
    fps: int
    payload_bytes: int
    traffic_seed: str
    trace_id: str
    generator_version: str
    frames_sent: int
    datagrams_sent: int
    bytes_sent: int
    average_mbit_s: float
    first_send_ns: int | None
    last_send_ns: int | None


def _frame_weight(
    frame_index: int,
    fps: int,
    scenario: str,
    rng: random.Random,
) -> float:
    burst = SCENARIO_BURST.get(scenario, SCENARIO_BURST["city"])
    keyframe = frame_index % fps == 0
    keyframe_factor = 2.2 + burst * 0.8
    if keyframe:
        return keyframe_factor * rng.uniform(0.9, 1.1)
    p_frame_base = max(0.25, (fps - keyframe_factor) / max(1, fps - 1))
    return max(0.2, p_frame_base * rng.normalvariate(1.0, 0.10 + burst * 0.05))


def _frame_size_bytes(
    frame_index: int,
    fps: int,
    bitrate_mbit_s: float,
    scenario: str,
    rng: random.Random,
) -> int:
    average = bitrate_mbit_s * 1_000_000 / 8 / fps
    return max(1, int(average * _frame_weight(frame_index, fps, scenario, rng)))


def _frame_size_schedule(
    frames: int,
    fps: int,
    bitrate_mbit_s: float,
    scenario: str,
    rng: random.Random,
) -> list[int]:
    if frames <= 0:
        return []
    weights = [_frame_weight(index, fps, scenario, rng) for index in range(frames)]
    target_bytes = bitrate_mbit_s * 1_000_000 / 8 * (frames / fps)
    scale = target_bytes / max(sum(weights), 1)
    sizes = [max(1, int(weight * scale)) for weight in weights]
    remainder = round(target_bytes - sum(sizes))
    index = 0
    while remainder > 0:
        sizes[index % len(sizes)] += 1
        remainder -= 1
        index += 1
    return sizes


def _packet(
    run_id: str,
    path_id: str,
    frame_id: int,
    fragment: int,
    fragments: int,
    send_ns: int,
) -> bytes:
    header = {
        "run_id": run_id,
        "path_id": path_id,
        "frame_id": frame_id,
        "fragment_index": fragment,
        "fragment_count": fragments,
        "send_ns": send_ns,
    }
    return b"LTAPFRAME " + json.dumps(header, separators=(",", ":")).encode() + b"\n"


def run_video_udp_probe(
    host: str,
    port: int,
    run_id: str,
    path_id: str,
    duration_seconds: int,
    bitrate_mbit_s: float,
    fps: int = 25,
    resolution: str = "1080p",
    scenario: str = "city",
    payload_bytes: int = 1200,
    traffic_seed: str = "video-trace-v1",
    trace_id: str = "synthetic-city-v1",
    generator_version: str = "synthetic-video-v2",
    should_cancel: Callable[[], bool] | None = None,
) -> VideoUdpProbeResult:
    if fps <= 0:
        raise ValueError("fps must be positive")
    if payload_bytes < 300:
        raise ValueError("payload_bytes is too small for frame headers")
    rng = random.Random(f"{traffic_seed}:{trace_id}:{scenario}:{fps}:{bitrate_mbit_s}")
    frame_interval = 1 / fps
    planned_frame_sizes = _frame_size_schedule(
        duration_seconds * fps,
        fps,
        bitrate_mbit_s,
        scenario,
        rng,
    )
    start = time.monotonic()
    deadline = start + duration_seconds
    next_frame = start
    frames_sent = 0
    datagrams_sent = 0
    bytes_sent = 0
    first_send_ns = None
    last_send_ns = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1)
        sock.connect((host, port))
        while (
            frames_sent < len(planned_frame_sizes)
            and time.monotonic() < deadline
            and not (should_cancel and should_cancel())
        ):
            frame_bytes = planned_frame_sizes[frames_sent]
            fragments = max(1, (frame_bytes + payload_bytes - 1) // payload_bytes)
            frame_send_ns = time.time_ns()
            if first_send_ns is None:
                first_send_ns = frame_send_ns
            last_send_ns = frame_send_ns
            remaining_frame_bytes = frame_bytes
            for fragment in range(fragments):
                if should_cancel and should_cancel():
                    break
                packet = _packet(run_id, path_id, frames_sent, fragment, fragments, frame_send_ns)
                packet_size = min(payload_bytes, remaining_frame_bytes)
                if len(packet) < packet_size:
                    packet += b"\0" * (packet_size - len(packet))
                sock.send(packet)
                datagrams_sent += 1
                bytes_sent += len(packet)
                remaining_frame_bytes = max(0, remaining_frame_bytes - packet_size)
            frames_sent += 1
            next_frame += frame_interval
            sleep_for = next_frame - time.monotonic()
            while sleep_for > 0 and not (should_cancel and should_cancel()):
                time.sleep(min(sleep_for, 0.05))
                sleep_for = next_frame - time.monotonic()
    elapsed = max(time.monotonic() - start, 0.001)
    return VideoUdpProbeResult(
        target_host=host,
        target_port=port,
        run_id=run_id,
        path_id=path_id,
        resolution=resolution,
        scenario=scenario,
        duration_seconds=elapsed,
        requested_duration_seconds=duration_seconds,
        bitrate_mbit_s=bitrate_mbit_s,
        fps=fps,
        payload_bytes=payload_bytes,
        traffic_seed=traffic_seed,
        trace_id=trace_id,
        generator_version=generator_version,
        frames_sent=frames_sent,
        datagrams_sent=datagrams_sent,
        bytes_sent=bytes_sent,
        average_mbit_s=bytes_sent * 8 / elapsed / 1_000_000,
        first_send_ns=first_send_ns,
        last_send_ns=last_send_ns,
    )
