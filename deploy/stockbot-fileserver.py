#!/usr/bin/env python3
import base64
import html
import json
import os
import posixpath
import re
import shutil
import socketserver
import threading
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

USERNAME = os.environ.get("STOCKBOT_FILESERVER_USER", "madis")
PASSWORD = os.environ.get("STOCKBOT_FILESERVER_PASSWORD", "")
UPLOAD_DIR = Path(os.environ.get("STOCKBOT_FILESERVER_UPLOAD_DIR", "/home/madis/uploads")).resolve()
MAX_FORM_SIZE = int(
    os.environ.get("STOCKBOT_FILESERVER_MAX_FORM_SIZE", str(2 * 1024 * 1024 * 1024))
)
RUNS: dict[str, list[dict]] = {}
VIDEO_FRAMES: dict[str, dict] = {}
RESERVATIONS: dict[str, dict] = {}
STARTED_AT = time.time()
RUNS_LOCK = threading.Lock()
MAX_ACTIVE_VIDEO_FRAMES_PER_PATH = int(
    os.environ.get("STOCKBOT_VIDEO_MAX_ACTIVE_FRAMES_PER_PATH", "5000")
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def safe_target(raw_path: str) -> Path:
    parsed = urlparse(raw_path)
    decoded = unquote(parsed.path)
    normalized = posixpath.normpath(decoded).lstrip("/")
    if not normalized or normalized == ".":
        raise ValueError("missing filename")
    target = (UPLOAD_DIR / normalized).resolve()
    if target != UPLOAD_DIR and UPLOAD_DIR not in target.parents:
        raise ValueError("invalid path")
    return target


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def collect_metrics() -> dict:
    disk = shutil.disk_usage("/")
    load1, load5, load15 = os.getloadavg()
    networks = []
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except OSError:
        lines = []
    for line in lines:
        name, counters = line.split(":", 1)
        parts = counters.split()
        sysfs = Path("/sys/class/net") / name.strip()
        carrier = read_text(sysfs / "carrier")
        speed = read_int(sysfs / "speed")
        networks.append(
            {
                "name": name.strip(),
                "rx_bytes": int(parts[0]),
                "tx_bytes": int(parts[8]),
                "rx_errors": int(parts[2]),
                "tx_errors": int(parts[10]),
                "rx_drops": int(parts[3]),
                "tx_drops": int(parts[11]),
                "operstate": read_text(sysfs / "operstate"),
                "carrier": None if carrier is None else carrier == "1",
                "speed_mbit_s": speed if speed and speed > 0 else None,
            }
        )
    return {
        "uptime_seconds": max(0.0, time.time() - STARTED_AT),
        "load_average": {"1m": load1, "5m": load5, "15m": load15},
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
        "network": networks,
    }


def prune_expired_reservations() -> None:
    now = time.time()
    expired = [
        reservation_id
        for reservation_id, reservation in RESERVATIONS.items()
        if now - reservation["created_epoch"] > reservation["ttl_seconds"]
    ]
    for reservation_id in expired:
        RESERVATIONS.pop(reservation_id, None)


def public_reservation(reservation: dict) -> dict:
    return {key: value for key, value in reservation.items() if key != "token"}


def run_matches_reservation(reserved_run_id: str | None, traffic_run_id: str) -> bool:
    if not reserved_run_id:
        return True
    return traffic_run_id == reserved_run_id or traffic_run_id.startswith(f"{reserved_run_id}-")


def reservation_authorized(run_id: str, token: str | None) -> tuple[bool, HTTPStatus, str]:
    prune_expired_reservations()
    if not token:
        return False, HTTPStatus.UNAUTHORIZED, "missing reservation token"
    with RUNS_LOCK:
        for reservation in RESERVATIONS.values():
            if reservation.get("token") != token:
                continue
            if not run_matches_reservation(reservation.get("run_id"), run_id):
                return False, HTTPStatus.FORBIDDEN, "reservation run mismatch"
            return True, HTTPStatus.OK, "ok"
    return False, HTTPStatus.FORBIDDEN, "invalid reservation token"


def record_udp_datagram(
    run_id: str,
    source: str,
    port: int,
    size: int,
    sequence: int | None = None,
    send_ns: int | None = None,
    token_present: bool = False,
) -> None:
    now = datetime.now(UTC)
    now_ns = time.time_ns()
    with RUNS_LOCK:
        records = RUNS.setdefault(run_id, [])
        record = next(
            (
                item
                for item in records
                if item.get("protocol") == "udp" and item.get("source") == source
            ),
            None,
        )
        if record is None:
            record = {
                "request_id": f"udp-{uuid4().hex[:12]}",
                "run_id": run_id,
                "protocol": "udp",
                "source": source,
                "destination_port": port,
                "bytes_received": 0,
                "datagrams_received": 0,
                "unique_datagrams": 0,
                "duplicates": 0,
                "out_of_order": 0,
                "missing_datagrams": 0,
                "first_sequence": None,
                "last_sequence": None,
                "max_sequence": None,
                "sequence_version": 2 if sequence is not None else 1,
                "started_at": now.isoformat(),
                "ended_at": now.isoformat(),
                "start_epoch_ns": now_ns,
                "last_epoch_ns": now_ns,
                "duration_seconds": 0.000001,
                "average_mbit_s": 0.0,
                "delivered_mbit_s": 0.0,
                "sender_timestamp_present": send_ns is not None,
                "_seen_sequences": set(),
                "_bucket_seen_sequences": {},
                "intervals": [],
                "token_present": token_present,
            }
            records.append(record)
        record["token_present"] = bool(record.get("token_present") or token_present)
        record["bytes_received"] += size
        record["datagrams_received"] += 1
        duplicate = False
        previous_sequence = record.get("last_sequence")
        if sequence is None:
            record["unique_datagrams"] += 1
        else:
            seen_sequences = record.setdefault("_seen_sequences", set())
            if sequence in seen_sequences:
                record["duplicates"] += 1
                duplicate = True
            else:
                seen_sequences.add(sequence)
                record["unique_datagrams"] += 1
                if record.get("first_sequence") is None:
                    record["first_sequence"] = sequence
                if previous_sequence is not None and sequence < int(previous_sequence):
                    record["out_of_order"] += 1
                record["last_sequence"] = sequence
                record["max_sequence"] = max(int(record.get("max_sequence") or sequence), sequence)
                first_sequence = int(record.get("first_sequence") or 0)
                max_sequence = int(record.get("max_sequence") or sequence)
                record["missing_datagrams"] = max(
                    0, (max_sequence - first_sequence + 1) - int(record["unique_datagrams"])
                )
        started_ns = int(record.get("start_epoch_ns") or now_ns)
        bucket_index = int(max(0, now_ns - started_ns) // 1_000_000_000)
        intervals = record.setdefault("intervals", [])
        while len(intervals) <= bucket_index:
            intervals.append(
                {
                    "offset_seconds": len(intervals),
                    "bytes": 0,
                    "datagrams_received": 0,
                    "unique_datagrams": 0,
                    "duplicates": 0,
                    "out_of_order": 0,
                    "delivered_mbit_s": 0.0,
                }
            )
        bucket = intervals[bucket_index]
        bucket["bytes"] += size
        bucket["datagrams_received"] += 1
        bucket["_start_epoch_ns"] = started_ns + bucket_index * 1_000_000_000
        bucket["_last_epoch_ns"] = now_ns
        if sequence is None:
            bucket["unique_datagrams"] += 1
        else:
            bucket_seen = record.setdefault("_bucket_seen_sequences", {}).setdefault(
                bucket_index, set()
            )
            if duplicate or sequence in bucket_seen:
                bucket["duplicates"] += 1
            else:
                bucket_seen.add(sequence)
                bucket["unique_datagrams"] += 1
            if previous_sequence is not None and sequence < int(previous_sequence):
                bucket["out_of_order"] += 1
        duration = max((now_ns - started_ns) / 1_000_000_000, 0.000001)
        record["ended_at"] = now.isoformat()
        record["last_epoch_ns"] = now_ns
        record["duration_seconds"] = duration
        record["average_mbit_s"] = record["bytes_received"] * 8 / duration / 1_000_000
        record["delivered_mbit_s"] = record["average_mbit_s"]
        bucket_duration = max(
            (int(bucket["_last_epoch_ns"]) - int(bucket["_start_epoch_ns"])) / 1_000_000_000,
            0.000001,
        )
        bucket["delivered_mbit_s"] = bucket["bytes"] * 8 / bucket_duration / 1_000_000


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def public_run_records(run_id: str) -> list[dict]:
    rows = []
    with RUNS_LOCK:
        for record in RUNS.get(run_id, []):
            row = {key: value for key, value in record.items() if not key.startswith("_")}
            if row.get("protocol") == "udp":
                row["intervals"] = [
                    {key: value for key, value in bucket.items() if not key.startswith("_")}
                    for bucket in row.get("intervals", [])
                ]
                unique = int(row.get("unique_datagrams") or row.get("datagrams_received") or 0)
                missing = int(row.get("missing_datagrams") or 0)
                expected = unique + missing
                row["packet_loss_percent"] = missing / expected * 100 if expected else 0.0
            rows.append(row)
    return rows


def _new_video_path(source: str, port: int, now_wall: datetime) -> dict:
    now_iso_value = now_wall.replace(microsecond=0).isoformat()
    return {
        "source": source,
        "destination_port": port,
        "first_seen_at": now_iso_value,
        "last_seen_at": now_iso_value,
        "bytes_received": 0,
        "datagrams_received": 0,
        "frames": {},
        "stats": {
            "frames_seen": 0,
            "frames_complete": 0,
            "frames_partial": 0,
            "fragment_arrival_span_ms": [],
            "first_arrival_ns_by_frame": {},
            "first_send_ns_by_frame": {},
            "finalized_frame_ids": set(),
        },
    }


def _finalize_video_frame(path: dict, frame_id: int, frame: dict) -> None:
    stats = path["stats"]
    if int(frame_id) in stats["finalized_frame_ids"]:
        return
    stats["finalized_frame_ids"].add(int(frame_id))
    fragment_count = int(frame.get("fragment_count") or 0)
    fragments = frame.get("fragments") or set()
    if fragment_count and len(fragments) >= fragment_count:
        stats["frames_complete"] += 1
        stats["fragment_arrival_span_ms"].append(
            (int(frame["last_arrival_ns"]) - int(frame["first_arrival_ns"])) / 1_000_000
        )
        stats["first_arrival_ns_by_frame"][int(frame_id)] = int(frame["first_arrival_ns"])
        if frame.get("first_send_ns") is not None:
            stats["first_send_ns_by_frame"][int(frame_id)] = int(frame["first_send_ns"])
    else:
        stats["frames_partial"] += 1


def _prune_video_frames(path: dict) -> None:
    frames = path["frames"]
    while len(frames) > MAX_ACTIVE_VIDEO_FRAMES_PER_PATH:
        oldest_id = min(frames)
        _finalize_video_frame(path, int(oldest_id), frames.pop(oldest_id))


def _live_video_summary_locked(run_id: str) -> dict:
    raw = VIDEO_FRAMES.get(run_id, {"paths": {}})
    path_summaries = {}
    for path_id, path in raw.get("paths", {}).items():
        frames = path.get("frames", {})
        stats = path.get("stats", {})
        active_complete = 0
        active_partial = 0
        for frame in frames.values():
            fragment_count = int(frame.get("fragment_count") or 0)
            received = len(frame.get("fragments") or [])
            if fragment_count and received >= fragment_count:
                active_complete += 1
            else:
                active_partial += 1
        frames_seen = int(stats.get("frames_seen") or 0)
        frames_complete = int(stats.get("frames_complete") or 0) + active_complete
        frames_partial = int(stats.get("frames_partial") or 0) + active_partial
        path_summaries[path_id] = {
            "path_id": path_id,
            "source": path.get("source"),
            "destination_port": path.get("destination_port"),
            "first_seen_at": path.get("first_seen_at"),
            "last_seen_at": path.get("last_seen_at"),
            "bytes_received": path.get("bytes_received", 0),
            "datagrams_received": path.get("datagrams_received", 0),
            "frames_seen": frames_seen,
            "frames_complete": frames_complete,
            "frames_partial": frames_partial,
            "frames_incomplete": frames_partial,
            "completion_among_seen_percent": (
                frames_complete / frames_seen * 100 if frames_seen else None
            ),
        }
    return {
        "run_id": run_id,
        "summary_mode": "live",
        "paths": path_summaries,
        "paired_frames_complete": None,
        "first_arrival_winners": {},
        "first_arrival_ties": None,
    }


def record_video_frame_datagram(header: dict, source: str, port: int, size: int) -> None:
    run_id = str(header.get("run_id") or "")
    path_id = str(header.get("path_id") or "")
    if not run_id or not path_id:
        return
    ok, _status, _message = reservation_authorized(run_id, header.get("token"))
    if not ok:
        return
    try:
        frame_id = int(header["frame_id"])
        fragment_index = int(header["fragment_index"])
        fragment_count = int(header["fragment_count"])
        send_ns = int(header["send_ns"]) if header.get("send_ns") is not None else None
    except (KeyError, TypeError, ValueError):
        return
    if frame_id < 0 or fragment_count < 1 or fragment_index < 0 or fragment_index >= fragment_count:
        return
    now_ns = time.monotonic_ns()
    now_wall = datetime.now(UTC)
    with RUNS_LOCK:
        run = VIDEO_FRAMES.setdefault(run_id, {"paths": {}})
        path = run["paths"].setdefault(path_id, _new_video_path(source, port, now_wall))
        path["source"] = source
        path["destination_port"] = port
        path["last_seen_at"] = now_wall.replace(microsecond=0).isoformat()
        if frame_id in path["stats"]["finalized_frame_ids"]:
            return
        path["bytes_received"] += size
        path["datagrams_received"] += 1
        frames = path["frames"]
        is_new_frame = frame_id not in frames
        frame = path["frames"].setdefault(
            frame_id,
            {
                "frame_id": frame_id,
                "fragment_count": fragment_count,
                "fragments": set(),
                "first_arrival_ns": now_ns,
                "last_arrival_ns": now_ns,
                "first_send_ns": send_ns,
            },
        )
        if is_new_frame:
            path["stats"]["frames_seen"] += 1
        frame["fragment_count"] = max(int(frame["fragment_count"]), fragment_count)
        frame["fragments"].add(fragment_index)
        frame["first_arrival_ns"] = min(int(frame["first_arrival_ns"]), now_ns)
        frame["last_arrival_ns"] = max(int(frame["last_arrival_ns"]), now_ns)
        if frame.get("first_send_ns") is None and send_ns is not None:
            frame["first_send_ns"] = send_ns
        if len(frame["fragments"]) >= int(frame["fragment_count"]):
            _finalize_video_frame(path, frame_id, frames.pop(frame_id))
        _prune_video_frames(path)


def summarize_video_frames(run_id: str, finalize: bool = False, delete: bool = False) -> dict:
    with RUNS_LOCK:
        if not finalize and not delete:
            return _live_video_summary_locked(run_id)
        raw = VIDEO_FRAMES.get(run_id, {"paths": {}})
        paths = raw.get("paths", {})
        path_summaries = {}
        complete_by_path = {}
        first_by_path = {}
        send_by_path = {}
        for path_id, path in paths.items():
            frames = path.get("frames", {})
            stats = path.get("stats", {})
            active_complete = 0
            active_partial = 0
            active_completion_ms = []
            active_first_arrivals = {}
            active_first_sends = {}
            for frame_id, frame in list(frames.items()):
                fragment_count = int(frame.get("fragment_count") or 0)
                received = len(frame.get("fragments") or [])
                if finalize:
                    _finalize_video_frame(path, int(frame_id), frames.pop(frame_id))
                    continue
                if fragment_count and received >= fragment_count:
                    active_complete += 1
                    active_completion_ms.append(
                        (int(frame["last_arrival_ns"]) - int(frame["first_arrival_ns"])) / 1_000_000
                    )
                    active_first_arrivals[int(frame_id)] = int(frame["first_arrival_ns"])
                    if frame.get("first_send_ns") is not None:
                        active_first_sends[int(frame_id)] = int(frame["first_send_ns"])
                else:
                    active_partial += 1
            first_arrivals = stats.get("first_arrival_ns_by_frame") or {}
            first_sends = stats.get("first_send_ns_by_frame") or {}
            completion_ms = [*(stats.get("fragment_arrival_span_ms") or []), *active_completion_ms]
            path_first_arrivals = {int(k): int(v) for k, v in first_arrivals.items()}
            path_first_arrivals.update(active_first_arrivals)
            path_first_sends = {int(k): int(v) for k, v in first_sends.items()}
            path_first_sends.update(active_first_sends)
            complete_by_path[path_id] = set(path_first_arrivals)
            first_by_path[path_id] = path_first_arrivals
            send_by_path[path_id] = path_first_sends
            path_summaries[path_id] = {
                "path_id": path_id,
                "source": path.get("source"),
                "destination_port": path.get("destination_port"),
                "first_seen_at": path.get("first_seen_at"),
                "last_seen_at": path.get("last_seen_at"),
                "bytes_received": path.get("bytes_received", 0),
                "datagrams_received": path.get("datagrams_received", 0),
                "frames_seen": stats.get("frames_seen", 0),
                "frames_complete": stats.get("frames_complete", 0) + active_complete,
                "frames_partial": stats.get("frames_partial", 0) + active_partial,
                "frames_incomplete": stats.get("frames_partial", 0) + active_partial,
                "fragment_arrival_span_ms_p50": percentile(completion_ms, 0.50),
                "fragment_arrival_span_ms_p95": percentile(completion_ms, 0.95),
                "fragment_arrival_span_ms_p99": percentile(completion_ms, 0.99),
                "fragment_arrival_span_ms_max": max(completion_ms, default=None),
                "frame_completion_ms_p50": percentile(completion_ms, 0.50),
                "frame_completion_ms_p95": percentile(completion_ms, 0.95),
                "frame_completion_ms_p99": percentile(completion_ms, 0.99),
                "frame_completion_ms_max": max(completion_ms, default=None),
            }
        paired_diffs = []
        corrected_diffs = []
        winners: dict[str, int] = {}
        ties = 0
        if len(first_by_path) >= 2:
            ids = sorted(first_by_path)[:2]
            common = complete_by_path.get(ids[0], set()) & complete_by_path.get(ids[1], set())
            either = complete_by_path.get(ids[0], set()) | complete_by_path.get(ids[1], set())
            left_only = complete_by_path.get(ids[0], set()) - complete_by_path.get(ids[1], set())
            right_only = complete_by_path.get(ids[1], set()) - complete_by_path.get(ids[0], set())
            for frame_id in common:
                diff_ms = (
                    first_by_path[ids[0]][frame_id] - first_by_path[ids[1]][frame_id]
                ) / 1_000_000
                paired_diffs.append(diff_ms)
                send_0 = send_by_path.get(ids[0], {}).get(frame_id)
                send_1 = send_by_path.get(ids[1], {}).get(frame_id)
                comparison_ms = diff_ms
                if send_0 is not None and send_1 is not None:
                    comparison_ms = diff_ms - ((send_0 - send_1) / 1_000_000)
                    corrected_diffs.append(comparison_ms)
                if comparison_ms == 0:
                    ties += 1
                else:
                    winner = ids[0] if comparison_ms < 0 else ids[1]
                    winners[winner] = winners.get(winner, 0) + 1
            dual_path = {
                "paths": ids,
                "complete_on_both": len(common),
                "complete_on_either": len(either),
                f"{ids[0]}_only_complete": len(left_only),
                f"{ids[1]}_only_complete": len(right_only),
                "complete_frame_ids_by_path": {
                    ids[0]: sorted(complete_by_path.get(ids[0], set())),
                    ids[1]: sorted(complete_by_path.get(ids[1], set())),
                },
            }
        else:
            dual_path = {}
        summary = {
            "run_id": run_id,
            "summary_mode": "final" if finalize else "full",
            "paths": path_summaries,
            "paired_frames_complete": len(paired_diffs),
            "first_arrival_winners": winners,
            "first_arrival_ties": ties,
            "dual_path": dual_path,
            "path_arrival_delta_ms_p50": percentile([abs(v) for v in paired_diffs], 0.50),
            "path_arrival_delta_ms_p95": percentile([abs(v) for v in paired_diffs], 0.95),
            "path_arrival_delta_ms_p99": percentile([abs(v) for v in paired_diffs], 0.99),
            "path_arrival_delta_ms_max": max([abs(v) for v in paired_diffs], default=None),
            "corrected_path_arrival_delta_ms_p50": percentile(
                [abs(v) for v in corrected_diffs], 0.50
            ),
            "corrected_path_arrival_delta_ms_p95": percentile(
                [abs(v) for v in corrected_diffs], 0.95
            ),
            "corrected_path_arrival_delta_ms_p99": percentile(
                [abs(v) for v in corrected_diffs], 0.99
            ),
            "corrected_path_arrival_delta_ms_max": max(
                [abs(v) for v in corrected_diffs], default=None
            ),
        }
        if delete:
            VIDEO_FRAMES.pop(run_id, None)
        return summary


def record_tcp_upload(
    run_id: str,
    source: str,
    port: int,
    started: datetime,
    ended: datetime,
    bytes_received: int,
    complete: bool,
    token_present: bool,
) -> dict:
    duration = max((ended - started).total_seconds(), 0.000001)
    record = {
        "request_id": f"upload-{uuid4().hex[:12]}",
        "run_id": run_id,
        "protocol": "tcp",
        "source": source,
        "destination_port": port,
        "bytes_received": bytes_received,
        "complete": complete,
        "started_at": started.replace(microsecond=0).isoformat(),
        "ended_at": ended.replace(microsecond=0).isoformat(),
        "duration_seconds": duration,
        "average_mbit_s": bytes_received * 8 / duration / 1_000_000,
        "token_present": token_present,
    }
    with RUNS_LOCK:
        RUNS.setdefault(run_id, []).append(record)
    return record


class UdpUploadHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = self.request[0]
        header, _, _body = data.partition(b"\n")
        if header.startswith(b"LTAPFRAME "):
            try:
                payload = json.loads(header.removeprefix(b"LTAPFRAME ").decode("utf-8"))
            except json.JSONDecodeError:
                return
            record_video_frame_datagram(
                payload, self.client_address[0], self.server.server_address[1], len(data)
            )
            return
        if not header.startswith(b"LTAPUDP "):
            return
        header_text = header.removeprefix(b"LTAPUDP ").decode("utf-8", errors="replace").strip()
        sequence = None
        send_ns = None
        if header_text.startswith("{"):
            try:
                udp_header = json.loads(header_text)
            except json.JSONDecodeError:
                return
            run_id = str(udp_header.get("run_id") or "")
            if udp_header.get("sequence") is not None:
                sequence = int(udp_header["sequence"])
            if udp_header.get("send_ns") is not None:
                send_ns = int(udp_header["send_ns"])
            ok, _status, _message = reservation_authorized(run_id, udp_header.get("token"))
            if not ok:
                return
            token_present = bool(udp_header.get("token"))
        else:
            run_id = header_text
            ok, _status, _message = reservation_authorized(run_id, None)
            if not ok:
                return
            token_present = False
        if not run_id:
            return
        record_udp_datagram(
            run_id,
            self.client_address[0],
            self.server.server_address[1],
            len(data),
            sequence=sequence,
            send_ns=send_ns,
            token_present=token_present,
        )


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "StockbotFileServer/1.1"

    def authenticated(self) -> bool:
        if not PASSWORD:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:
            return False
        user, sep, password = decoded.partition(":")
        return sep == ":" and user == USERNAME and password == PASSWORD

    def require_auth(self) -> bool:
        if self.authenticated():
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="stockbot files"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authentication required.\n")
        return False

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, status: HTTPStatus, payload: dict | list) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def maybe_handle_api_get(self) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path
        prune_expired_reservations()
        if path == "/api/v1/health":
            self.send_json(
                HTTPStatus.OK, {"ok": True, "utc": now_iso(), "service": "stockbot-testnode"}
            )
            return True
        if path == "/api/v1/status":
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "utc": now_iso(),
                    "started_at_epoch": STARTED_AT,
                    "uptime_seconds": max(0.0, time.time() - STARTED_AT),
                    "active_reservations": [
                        public_reservation(item) for item in RESERVATIONS.values()
                    ],
                    "known_runs": sorted(RUNS),
                },
            )
            return True
        if path == "/api/v1/capabilities":
            self.send_json(
                HTTPStatus.OK,
                {
                    "upload_sink": True,
                    "udp_upload_sink": True,
                    "udp_video_frame_probe": True,
                    "iperf3_external": False,
                    "irtt_external": False,
                    "reservations": True,
                    "legacy_authenticated_files": True,
                },
            )
            return True
        if path == "/api/v1/metrics":
            self.send_json(HTTPStatus.OK, collect_metrics())
            return True
        run_match = re.fullmatch(r"/api/v1/runs/([^/]+)", path)
        if run_match:
            run_id = unquote(run_match.group(1))
            self.send_json(
                HTTPStatus.OK,
                {"run_id": run_id, "connections": public_run_records(run_id)},
            )
            return True
        conn_match = re.fullmatch(r"/api/v1/runs/([^/]+)/connections", path)
        if conn_match:
            run_id = unquote(conn_match.group(1))
            self.send_json(HTTPStatus.OK, public_run_records(run_id))
            return True
        frame_match = re.fullmatch(r"/api/v1/runs/([^/]+)/video-frames", path)
        if frame_match:
            run_id = unquote(frame_match.group(1))
            query = parse_qs(parsed.query)
            finalize = query.get("finalize", ["false"])[0].lower() == "true"
            delete = query.get("delete", ["false"])[0].lower() == "true"
            self.send_json(HTTPStatus.OK, summarize_video_frames(run_id, finalize, delete))
            return True
        reservation_match = re.fullmatch(r"/api/v1/reservations/([^/]+)", path)
        if reservation_match:
            reservation_id = unquote(reservation_match.group(1))
            if reservation_id not in RESERVATIONS:
                self.send_json(HTTPStatus.NOT_FOUND, {"detail": "reservation not found"})
                return True
            self.send_json(HTTPStatus.OK, public_reservation(RESERVATIONS[reservation_id]))
            return True
        return False

    def do_GET(self):
        if self.maybe_handle_api_get():
            return
        if not self.require_auth():
            return
        parsed = urlparse(self.path)
        if parsed.path.startswith("/files/"):
            try:
                target = safe_target(parsed.path.removeprefix("/files/"))
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "file not found")
                return
            name = target.relative_to(UPLOAD_DIR).as_posix()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
            self.end_headers()
            with target.open("rb") as src:
                shutil.copyfileobj(src, self.wfile)
            return
        files = []
        for item in sorted(UPLOAD_DIR.rglob("*")):
            if item.is_file():
                rel = item.relative_to(UPLOAD_DIR)
                files.append((str(rel), item.stat().st_size))
        rows = "\n".join(
            f"<li><a href='/files/{quote(name)}'>{html.escape(name)}</a> ({size} bytes)</li>"
            for name, size in files
        )
        body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>stockbot files</title></head>
<body>
<h1>stockbot files</h1>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" required>
  <button type="submit">Upload</button>
</form>
<h2>Uploaded files</h2>
<ul>{rows}</ul>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        if self.path == "/api/v1/reservations":
            prune_expired_reservations()
            if RESERVATIONS:
                self.send_json(HTTPStatus.CONFLICT, {"detail": "test node already reserved"})
                return
            payload = self.read_json_body()
            reservation_id = f"res-{uuid4().hex[:12]}"
            RESERVATIONS[reservation_id] = {
                "id": reservation_id,
                "owner": payload.get("owner", "unknown"),
                "run_id": payload.get("run_id"),
                "created_at": now_iso(),
                "created_epoch": time.time(),
                "ttl_seconds": int(payload.get("ttl_seconds", 3600)),
                "token": f"tok-{uuid4().hex}",
            }
            self.send_json(HTTPStatus.OK, RESERVATIONS[reservation_id])
            return
        if not self.require_auth():
            return
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not content_type.startswith("multipart/form-data") or not match:
            self.send_error(HTTPStatus.BAD_REQUEST, "expected multipart/form-data")
            return
        boundary = ("--" + match.group(1)).encode("utf-8")
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_FORM_SIZE:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "file too large")
            return
        body = self.rfile.read(length)
        filename = None
        filedata = None
        for part in body.split(boundary):
            if b"\r\n\r\n" not in part:
                continue
            headers, data = part.split(b"\r\n\r\n", 1)
            if data.endswith(b"\r\n"):
                data = data[:-2]
            header_text = headers.decode("utf-8", errors="replace")
            if 'name="file"' not in header_text:
                continue
            name_match = re.search(r'filename="([^"]*)"', header_text)
            if name_match and name_match.group(1):
                filename = Path(name_match.group(1)).name
                filedata = data
                break
        if not filename or filedata is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing file")
            return
        target = (UPLOAD_DIR / filename).resolve()
        if UPLOAD_DIR not in target.parents:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid filename")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(filedata)
        self.send_response(HTTPStatus.CREATED)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"Uploaded {filename}\n".encode())

    def do_DELETE(self):
        reservation_match = re.fullmatch(r"/api/v1/reservations/([^/]+)", urlparse(self.path).path)
        if reservation_match:
            RESERVATIONS.pop(unquote(reservation_match.group(1)), None)
            self.send_json(HTTPStatus.OK, {"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_PATCH(self):
        renew_match = re.fullmatch(
            r"/api/v1/reservations/([^/]+)/renew",
            urlparse(self.path).path,
        )
        if renew_match:
            reservation_id = unquote(renew_match.group(1))
            prune_expired_reservations()
            if reservation_id not in RESERVATIONS:
                self.send_json(HTTPStatus.NOT_FOUND, {"detail": "reservation not found"})
                return
            payload = self.read_json_body()
            reservation = RESERVATIONS[reservation_id]
            reservation["created_at"] = now_iso()
            reservation["created_epoch"] = time.time()
            if payload.get("ttl_seconds") is not None:
                reservation["ttl_seconds"] = int(payload["ttl_seconds"])
            self.send_json(HTTPStatus.OK, public_reservation(reservation))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_PUT(self):
        upload_match = re.fullmatch(r"/upload/([^/]+)", urlparse(self.path).path)
        if upload_match:
            run_id = unquote(upload_match.group(1))
            ok, status, message = reservation_authorized(run_id, self.headers.get("X-Ltap-Token"))
            if not ok:
                self.send_json(status, {"detail": message})
                return
            started = datetime.now(UTC)
            length = int(self.headers.get("Content-Length", "0"))
            remaining = length
            bytes_received = 0
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                bytes_received += len(chunk)
                remaining -= len(chunk)
            ended = datetime.now(UTC)
            complete = remaining == 0
            record = record_tcp_upload(
                run_id,
                self.client_address[0],
                self.server.server_port,
                started,
                ended,
                bytes_received,
                complete,
                bool(self.headers.get("X-Ltap-Token")),
            )
            if not complete:
                self.send_json(HTTPStatus.ACCEPTED, record)
                return
            self.send_json(HTTPStatus.OK, record)
            return
        if not self.require_auth():
            return
        try:
            target = safe_target(self.path)
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        length = int(self.headers.get("Content-Length", "0"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining:
            self.send_error(HTTPStatus.BAD_REQUEST, "incomplete upload")
            return
        self.send_response(HTTPStatus.CREATED)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"Uploaded {target.relative_to(UPLOAD_DIR)}\n".encode())

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)


if __name__ == "__main__":
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("STOCKBOT_FILESERVER_PORT", "8088"))
    host = os.environ.get("STOCKBOT_FILESERVER_HOST", "0.0.0.0")
    udp_port = int(os.environ.get("STOCKBOT_FILESERVER_UDP_PORT", str(port)))
    udp_server = socketserver.ThreadingUDPServer((host, udp_port), UdpUploadHandler)
    threading.Thread(target=udp_server.serve_forever, daemon=True).start()
    ThreadingHTTPServer((host, port), UploadHandler).serve_forever()
