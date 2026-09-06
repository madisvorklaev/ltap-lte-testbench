"""RUTX12 moving-drive helpers.

This module keeps the RUTX12/RB4011 moving-drive worker focused on evidence
classification and public/private separation. Live collection is intentionally
thin; parsing and verdict logic live here so tests can lock down the safety
rules before a road run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "rutx12-drive-v1"
PINNED_BASE_COMMIT = "b3689512f91683fdcaf62f49f333cb2c35823cff"
SERVER_IPV4 = "217.18.95.142"
SOURCE_A = "192.168.101.201"
SOURCE_B = "192.168.101.202"
PORT_PAIRS = [(5201, 5202), (5203, 5204), (5205, 5206), (5207, 5208)]
REQUIRED_RATE_BPS = 5_000_000
REQUIRED_PAYLOAD_BYTES = 1200
MAX_DUAL_START_SKEW_S = 2.0
TARGET_DUAL_START_SKEW_S = 0.250


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def stable_hash(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path_hash = hashlib.sha1(str(path).encode()).hexdigest()[:8]
    tmp = path.with_suffix(path.suffix + f".{path_hash}.tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        row = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write(row + "\n")
        handle.flush()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"parse_error": "INVALID_JSONL", "raw_line": line})
    return rows


def truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "enabled",
        "primary",
        "up",
        "connected",
        "registered",
    }:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "down", "disconnected", "unregistered"}:
        return False
    return None


def number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def selected_modem(modems: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    modem_list = list(modems)
    primaries = [
        m
        for m in modem_list
        if truthy(m.get("primary")) is True or truthy(m.get("is_primary")) is True
    ]
    if len(primaries) == 1:
        return primaries[0]
    active = [
        m
        for m in modem_list
        if truthy(m.get("data_connected") or m.get("connected") or m.get("packet_data")) is True
    ]
    return active[0] if len(active) == 1 else None


def pseudonym(prefix: str, raw_value: Any) -> str | None:
    if raw_value in (None, ""):
        return None
    return f"{prefix}-{hashlib.sha256(str(raw_value).encode()).hexdigest()[:10]}"


def normalize_modem_status(
    raw: dict[str, Any],
    router_label: str,
    utc: str | None = None,
) -> dict[str, Any]:
    cells = raw.get("cell_info") if isinstance(raw.get("cell_info"), list) else []
    ca = raw.get("ca_signal") if isinstance(raw.get("ca_signal"), list) else []
    registered = truthy(raw.get("registered"))
    if registered is None:
        status_text = str(raw.get("registration") or raw.get("status") or "").lower()
        registered = "registered" in status_text
    data_connected = truthy(
        raw.get("data_connected") or raw.get("packet_data") or raw.get("connected")
    )
    address = raw.get("ipv4_address") or raw.get("ip_address") or raw.get("address")
    route = raw.get("default_route") or raw.get("gateway") or raw.get("route")
    return {
        "utc": utc or utc_now(),
        "router": router_label,
        "modem_id": pseudonym("modem", raw.get("id") or raw.get("modem_id") or raw.get("imei")),
        "sim_id": pseudonym("sim", raw.get("sim_id") or raw.get("iccid") or raw.get("imsi")),
        "operator": raw.get("operator") or raw.get("network"),
        "rat": raw.get("rat") or raw.get("network_type"),
        "registered": bool(registered),
        "data_connected": data_connected,
        "selected_mobile_ipv4_present": bool(address),
        "default_route_present": bool(route),
        "primary_band": raw.get("band") or raw.get("primary_band"),
        "cell_info": cells,
        "ca_signal": ca,
        "rsrp_dbm": number_or_none(raw.get("rsrp")),
        "rsrq_db": number_or_none(raw.get("rsrq")),
        "sinr_db": number_or_none(raw.get("sinr")),
        "boot_id": raw.get("boot_id"),
        "interface": raw.get("interface"),
        "device": raw.get("device"),
    }


def normalize_gps(raw: dict[str, Any], utc: str | None = None) -> dict[str, Any]:
    lat_source = raw.get("lat") if "lat" in raw else raw.get("latitude")
    lon_source = raw.get("lon") if "lon" in raw else raw.get("longitude")
    lat = number_or_none(lat_source)
    lon = number_or_none(lon_source)
    valid = truthy(raw.get("valid") if "valid" in raw else raw.get("fix")) is True
    reasons = []
    if lat is None or lon is None:
        valid = False
        reasons.append("NO_NUMERIC_COORDINATE")
    elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
        valid = False
        reasons.append("COORDINATE_OUT_OF_RANGE")
    elif lat == 0 and lon == 0:
        valid = False
        reasons.append("ZERO_ZERO_COORDINATE")
    return {
        "utc": utc or utc_now(),
        "valid": valid,
        "latitude": lat if valid else None,
        "longitude": lon if valid else None,
        "speed_mps": number_or_none(raw.get("speed_mps") or raw.get("speed")),
        "course_deg": number_or_none(raw.get("course") or raw.get("bearing")),
        "satellites": number_or_none(raw.get("satellites")),
        "hdop": number_or_none(raw.get("hdop") or raw.get("accuracy")),
        "invalid_reason": ";".join(reasons) if reasons else None,
    }


def parse_ping_line(line: str) -> dict[str, Any] | None:
    seq_match = re.search(r"icmp_seq=(\d+)", line)
    seq = int(seq_match.group(1)) if seq_match else None
    if "no answer yet" in line.lower():
        return {"seq": seq, "status": "timeout", "rtt_ms": None}
    time_match = re.search(r"time=([0-9.]+)", line)
    if time_match:
        return {"seq": seq, "status": "reply", "rtt_ms": float(time_match.group(1))}
    if "duplicate" in line.lower():
        return {"seq": seq, "status": "duplicate", "rtt_ms": None}
    if "unreachable" in line.lower() or "error" in line.lower():
        return {"seq": seq, "status": "local_error", "rtt_ms": None}
    return None


def account_ping(lines: Iterable[str]) -> dict[str, Any]:
    seen: dict[int, str] = {}
    rtts: list[float] = []
    duplicates = 0
    local_errors = 0
    for line in lines:
        row = parse_ping_line(line)
        if not row or row["seq"] is None:
            continue
        seq = int(row["seq"])
        status = str(row["status"])
        if status == "reply":
            if seen.get(seq) == "reply":
                duplicates += 1
            seen[seq] = "reply"
            if row["rtt_ms"] is not None:
                rtts.append(float(row["rtt_ms"]))
        elif status == "duplicate":
            duplicates += 1
            seen.setdefault(seq, "duplicate")
        elif status == "local_error":
            local_errors += 1
            seen.setdefault(seq, "local_error")
        else:
            seen.setdefault(seq, "timeout")
    scheduled = max(seen) - min(seen) + 1 if seen else 0
    counts = {
        "reply": 0,
        "timeout": 0,
        "late": 0,
        "duplicate": duplicates,
        "local_error": local_errors,
    }
    if seen:
        for seq in range(min(seen), max(seen) + 1):
            counts[seen.get(seq, "timeout")] = counts.get(seen.get(seq, "timeout"), 0) + 1
    return {
        "scheduled": scheduled,
        "answered": counts["reply"],
        "timed_out": counts["timeout"],
        "duplicate": counts["duplicate"],
        "local_error": counts["local_error"],
        "loss_percent": (
            round((scheduled - counts["reply"]) / scheduled * 100.0, 6)
            if scheduled
            else None
        ),
        "rtt_p50_ms": percentile(rtts, 50),
        "rtt_p95_ms": percentile(rtts, 95),
        "rtt_p99_ms": percentile(rtts, 99),
        "rtt_max_ms": max(rtts) if rtts else None,
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct / 100
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - idx) + ordered[hi] * (idx - lo)


def parse_iperf_json_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "classification": "INFRASTRUCTURE_INVALID",
            "error": f"malformed iperf JSON: {exc}",
        }
    if data.get("error"):
        return {
            "valid": False,
            "classification": "INFRASTRUCTURE_INVALID",
            "error": str(data["error"]),
        }
    end = data.get("end") if isinstance(data.get("end"), dict) else {}
    sent = end.get("sum_sent") if isinstance(end.get("sum_sent"), dict) else {}
    received = end.get("sum_received")
    if not isinstance(received, dict):
        return {
            "valid": False,
            "classification": "UNATTRIBUTED_DELIVERY_UNMEASURED",
            "error": "missing receiver UDP summary",
            "sender_mbps": mbps(sent.get("bits_per_second")),
            "receiver_mbps": None,
            "loss_percent": None,
            "lost_packets": None,
            "packets": None,
        }
    return {
        "valid": True,
        "classification": "VALID_DELIVERY",
        "sender_mbps": mbps(sent.get("bits_per_second")),
        "receiver_mbps": mbps(received.get("bits_per_second")),
        "loss_percent": number_or_none(received.get("lost_percent")),
        "lost_packets": int(received.get("lost_packets") or 0),
        "packets": int(received.get("packets") or 0),
        "jitter_ms": number_or_none(received.get("jitter_ms")),
        "out_of_order_packets": int(
            received.get("out_of_order") or received.get("outoforder_packets") or 0
        ),
    }


def mbps(bits_per_second: Any) -> float | None:
    value = number_or_none(bits_per_second)
    return value / 1_000_000 if value is not None else None


def build_iperf_argv(server: str, port: int, source: str, seconds: int = 10) -> list[str]:
    return [
        "iperf3",
        "-4",
        "-c",
        server,
        "-p",
        str(port),
        "-B",
        source,
        "-u",
        "-b",
        str(REQUIRED_RATE_BPS),
        "-l",
        str(REQUIRED_PAYLOAD_BYTES),
        "-t",
        str(seconds),
        "-i",
        "1",
        "-J",
    ]


def validate_iperf_argv(argv: list[str]) -> list[str]:
    problems = []
    checks = {
        "-4": None,
        "-u": None,
        "-b": str(REQUIRED_RATE_BPS),
        "-l": str(REQUIRED_PAYLOAD_BYTES),
        "-i": "1",
        "-J": None,
    }
    for flag, expected in checks.items():
        if flag not in argv:
            problems.append(f"missing {flag}")
        elif expected is not None:
            idx = argv.index(flag)
            if idx + 1 >= len(argv) or argv[idx + 1] != expected:
                problems.append(f"{flag} must be {expected}")
    if "-P" in argv or "--parallel" in argv:
        problems.append("parallel streams are forbidden")
    return problems


def classify_epoch(
    path_a: dict[str, Any],
    path_b: dict[str, Any],
    skew_s: float | None = None,
    cross_egress: bool = False,
    partial: bool = False,
) -> str:
    if partial:
        return "PARTIAL_STOPPED_BY_USER"
    if cross_egress or (skew_s is not None and skew_s > MAX_DUAL_START_SKEW_S):
        return "INFRASTRUCTURE_INVALID"
    classes = {path_a.get("classification"), path_b.get("classification")}
    if classes == {"VALID_DELIVERY"}:
        return "VALID_DELIVERY"
    if "INFRASTRUCTURE_INVALID" in classes:
        return "INFRASTRUCTURE_INVALID"
    return "UNATTRIBUTED_DELIVERY_UNMEASURED"


def counter_delta(prev: int | None, cur: int | None) -> tuple[int | None, str | None]:
    if prev is None or cur is None:
        return None, "MISSING_COUNTER"
    if cur < prev:
        return None, "COUNTER_RESET"
    return cur - prev, None


@dataclass(frozen=True)
class OvernightPathSummary:
    valid_epochs: int
    packets: int
    lost_packets: int
    loss_percent: float | None
    mean_receiver_mbps: float | None
    median_epoch_loss: float | None
    p95_epoch_loss: float | None
    worst_epoch_loss: float | None


def recompute_overnight_soak(run_dir: Path) -> dict[str, Any]:
    epoch_dirs = sorted((run_dir / "epochs").glob("epoch-*"))
    full_epoch_dirs = [e for e in epoch_dirs if e.name != "epoch-0094"]
    paths = {"a": [], "b": []}
    paired_valid = []
    missing_receiver = {"a": 0, "b": 0}
    for epoch_dir in full_epoch_dirs:
        parsed = {}
        for path in ("a", "b"):
            iperf_path = epoch_dir / path / "iperf.json"
            text = (
                iperf_path.read_text(encoding="utf-8", errors="ignore")
                if iperf_path.exists()
                else ""
            )
            result = parse_iperf_json_text(text)
            parsed[path] = result
            if result["valid"]:
                paths[path].append(result)
            else:
                missing_receiver[path] += 1
        if parsed["a"]["valid"] and parsed["b"]["valid"]:
            paired_valid.append(parsed)
    both_good = 0
    for pair in paired_valid:
        good_a = receiver_good(pair["a"])
        good_b = receiver_good(pair["b"])
        if good_a and good_b:
            both_good += 1
    return {
        "session": run_dir.name,
        "scheduled_full_epochs": len(full_epoch_dirs),
        "right_censored_epochs": len(epoch_dirs) - len(full_epoch_dirs),
        "paired_valid_epochs": len(paired_valid),
        "both_paths_good_epochs": both_good,
        "missing_receiver_epochs": missing_receiver,
        "path_a": summarize_path(paths["a"]),
        "path_b": summarize_path(paths["b"]),
    }


def summarize_path(rows: list[dict[str, Any]]) -> dict[str, Any]:
    packets = sum(int(r.get("packets") or 0) for r in rows)
    lost = sum(int(r.get("lost_packets") or 0) for r in rows)
    mbps_values = [float(r["receiver_mbps"]) for r in rows if r.get("receiver_mbps") is not None]
    losses = [float(r["loss_percent"]) for r in rows if r.get("loss_percent") is not None]
    summary = OvernightPathSummary(
        valid_epochs=len(rows),
        packets=packets,
        lost_packets=lost,
        loss_percent=lost / packets * 100 if packets else None,
        mean_receiver_mbps=sum(mbps_values) / len(mbps_values) if mbps_values else None,
        median_epoch_loss=percentile(losses, 50),
        p95_epoch_loss=percentile(losses, 95),
        worst_epoch_loss=max(losses) if losses else None,
    )
    return summary.__dict__


def receiver_good(row: dict[str, Any]) -> bool:
    return (
        row["receiver_mbps"] is not None
        and row["receiver_mbps"] >= 4.90
        and (row["loss_percent"] or 0) < 2
    )


def write_checksums(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(root)}")
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
