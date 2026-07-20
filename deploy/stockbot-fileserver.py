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
from urllib.parse import quote, unquote, urlparse
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


def record_udp_datagram(run_id: str, source: str, port: int, size: int) -> None:
    now = datetime.now(UTC)
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
                "started_at": now.replace(microsecond=0).isoformat(),
                "ended_at": now.replace(microsecond=0).isoformat(),
                "duration_seconds": 0.000001,
                "average_mbit_s": 0.0,
                "token_present": False,
            }
            records.append(record)
        record["bytes_received"] += size
        record["datagrams_received"] += 1
        started = datetime.fromisoformat(record["started_at"])
        duration = max((now - started).total_seconds(), 0.000001)
        record["ended_at"] = now.replace(microsecond=0).isoformat()
        record["duration_seconds"] = duration
        record["average_mbit_s"] = record["bytes_received"] * 8 / duration / 1_000_000


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def record_video_frame_datagram(header: dict, source: str, port: int, size: int) -> None:
    run_id = str(header.get("run_id") or "")
    path_id = str(header.get("path_id") or "")
    if not run_id or not path_id:
        return
    try:
        frame_id = int(header["frame_id"])
        fragment_index = int(header["fragment_index"])
        fragment_count = int(header["fragment_count"])
    except (KeyError, TypeError, ValueError):
        return
    now_ns = time.monotonic_ns()
    now_wall = datetime.now(UTC)
    with RUNS_LOCK:
        run = VIDEO_FRAMES.setdefault(run_id, {"paths": {}})
        path = run["paths"].setdefault(
            path_id,
            {
                "source": source,
                "destination_port": port,
                "first_seen_at": now_wall.replace(microsecond=0).isoformat(),
                "last_seen_at": now_wall.replace(microsecond=0).isoformat(),
                "bytes_received": 0,
                "datagrams_received": 0,
                "frames": {},
            },
        )
        path["source"] = source
        path["destination_port"] = port
        path["last_seen_at"] = now_wall.replace(microsecond=0).isoformat()
        path["bytes_received"] += size
        path["datagrams_received"] += 1
        frame = path["frames"].setdefault(
            frame_id,
            {
                "frame_id": frame_id,
                "fragment_count": fragment_count,
                "fragments": set(),
                "first_arrival_ns": now_ns,
                "last_arrival_ns": now_ns,
            },
        )
        frame["fragment_count"] = max(int(frame["fragment_count"]), fragment_count)
        frame["fragments"].add(fragment_index)
        frame["first_arrival_ns"] = min(int(frame["first_arrival_ns"]), now_ns)
        frame["last_arrival_ns"] = max(int(frame["last_arrival_ns"]), now_ns)


def summarize_video_frames(run_id: str) -> dict:
    with RUNS_LOCK:
        raw = VIDEO_FRAMES.get(run_id, {"paths": {}})
        paths = raw.get("paths", {})
        path_summaries = {}
        complete_by_path = {}
        first_by_path = {}
        for path_id, path in paths.items():
            frames = path.get("frames", {})
            complete = []
            incomplete = 0
            completion_ms = []
            for frame_id, frame in frames.items():
                fragment_count = int(frame.get("fragment_count") or 0)
                received = len(frame.get("fragments") or [])
                if fragment_count and received >= fragment_count:
                    complete.append(int(frame_id))
                    completion_ms.append(
                        (int(frame["last_arrival_ns"]) - int(frame["first_arrival_ns"])) / 1_000_000
                    )
                    first_by_path.setdefault(path_id, {})[int(frame_id)] = int(
                        frame["first_arrival_ns"]
                    )
                else:
                    incomplete += 1
            complete_by_path[path_id] = set(complete)
            path_summaries[path_id] = {
                "path_id": path_id,
                "source": path.get("source"),
                "destination_port": path.get("destination_port"),
                "first_seen_at": path.get("first_seen_at"),
                "last_seen_at": path.get("last_seen_at"),
                "bytes_received": path.get("bytes_received", 0),
                "datagrams_received": path.get("datagrams_received", 0),
                "frames_seen": len(frames),
                "frames_complete": len(complete),
                "frames_incomplete": incomplete,
                "frame_completion_ms_p50": percentile(completion_ms, 0.50),
                "frame_completion_ms_p95": percentile(completion_ms, 0.95),
                "frame_completion_ms_p99": percentile(completion_ms, 0.99),
                "frame_completion_ms_max": max(completion_ms, default=None),
            }
        paired_diffs = []
        winners = {}
        if len(first_by_path) >= 2:
            ids = sorted(first_by_path)[:2]
            common = complete_by_path.get(ids[0], set()) & complete_by_path.get(ids[1], set())
            for frame_id in common:
                diff_ms = (
                    first_by_path[ids[0]][frame_id] - first_by_path[ids[1]][frame_id]
                ) / 1_000_000
                paired_diffs.append(diff_ms)
                winner = ids[0] if diff_ms < 0 else ids[1]
                winners[winner] = winners.get(winner, 0) + 1
        return {
            "run_id": run_id,
            "paths": path_summaries,
            "paired_frames_complete": len(paired_diffs),
            "first_arrival_winners": winners,
            "path_arrival_delta_ms_p50": percentile([abs(v) for v in paired_diffs], 0.50),
            "path_arrival_delta_ms_p95": percentile([abs(v) for v in paired_diffs], 0.95),
            "path_arrival_delta_ms_p99": percentile([abs(v) for v in paired_diffs], 0.99),
            "path_arrival_delta_ms_max": max([abs(v) for v in paired_diffs], default=None),
        }


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
        run_id = header.removeprefix(b"LTAPUDP ").decode("utf-8", errors="replace").strip()
        if not run_id:
            return
        record_udp_datagram(
            run_id, self.client_address[0], self.server.server_address[1], len(data)
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
                    "active_reservations": list(RESERVATIONS.values()),
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
            self.send_json(HTTPStatus.OK, {"run_id": run_id, "connections": RUNS.get(run_id, [])})
            return True
        conn_match = re.fullmatch(r"/api/v1/runs/([^/]+)/connections", path)
        if conn_match:
            run_id = unquote(conn_match.group(1))
            self.send_json(HTTPStatus.OK, RUNS.get(run_id, []))
            return True
        frame_match = re.fullmatch(r"/api/v1/runs/([^/]+)/video-frames", path)
        if frame_match:
            run_id = unquote(frame_match.group(1))
            self.send_json(HTTPStatus.OK, summarize_video_frames(run_id))
            return True
        reservation_match = re.fullmatch(r"/api/v1/reservations/([^/]+)", path)
        if reservation_match:
            reservation_id = unquote(reservation_match.group(1))
            if reservation_id not in RESERVATIONS:
                self.send_json(HTTPStatus.NOT_FOUND, {"detail": "reservation not found"})
                return True
            self.send_json(HTTPStatus.OK, RESERVATIONS[reservation_id])
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

    def do_PUT(self):
        upload_match = re.fullmatch(r"/upload/([^/]+)", urlparse(self.path).path)
        if upload_match:
            run_id = unquote(upload_match.group(1))
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
