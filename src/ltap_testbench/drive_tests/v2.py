"""ELMO LTE drive-test v2 parsing, timeline, and reporting helpers.

The worker writes raw append-only streams. This module keeps parsing and
post-processing deterministic so old coarse runs and new high-resolution runs
can be analyzed with the same entrypoint.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SKILL_NAME = "elmo-lte-drive-test"
SKILL_VERSION = "2.0"
GPS_STALE_S = 2.0
LTE_STALE_S = 2.0


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def parse_utc(value: str) -> dt.datetime:
    text = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def fmt_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        fh.flush()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"utc": None, "parse_error": "INVALID_JSONL", "raw_line": line})
    return rows


def parse_routeros_kv(raw: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw.splitlines():
        m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$", line)
        if m:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            data[m.group(1).lower()] = value
    return data


def _num(value: Any) -> float | None:
    if value is None:
        return None
    m = re.search(r"-?[0-9]+(?:\.[0-9]+)?", str(value))
    return float(m.group(0)) if m else None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def parse_coordinate(value: Any) -> float | None:
    """Parse decimal or DMS-like RouterOS coordinates."""
    if value is None:
        return None
    text = str(value).strip().strip('"')
    if not text:
        return None
    hemi = None
    hm = re.search(r"([NSEW])", text, re.I)
    if hm:
        hemi = hm.group(1).upper()
    decimal = re.fullmatch(r"[-+]?[0-9]+(?:\.[0-9]+)?", text)
    if decimal:
        out = float(text)
        # RouterOS LtAP GPS commonly emits NMEA-style ddmm.mmmm /
        # dddmm.mmmm without hemisphere letters, e.g. 5922.0159.
        if abs(out) > 180:
            sign = -1.0 if out < 0 else 1.0
            whole = abs(out)
            degrees = int(whole // 100)
            minutes = whole - degrees * 100
            out = sign * (degrees + minutes / 60.0)
    else:
        parts = [float(x) for x in re.findall(r"[-+]?[0-9]+(?:\.[0-9]+)?", text)]
        if not parts:
            return None
        sign = -1.0 if parts[0] < 0 else 1.0
        deg = abs(parts[0])
        minutes = parts[1] if len(parts) > 1 else 0.0
        seconds = parts[2] if len(parts) > 2 else 0.0
        out = sign * (deg + minutes / 60.0 + seconds / 3600.0)
    if hemi in {"S", "W"}:
        out = -abs(out)
    if hemi in {"N", "E"}:
        out = abs(out)
    return out


def parse_routeros_gps(raw: str, sample_completed_utc: str | None = None) -> dict[str, Any]:
    kv = parse_routeros_kv(raw)
    utc = sample_completed_utc or utc_now()
    valid_text = str(kv.get("valid") or kv.get("gps-valid") or kv.get("fix") or "").lower()
    valid = valid_text in {"yes", "true", "valid", "2d", "3d"}
    lat = parse_coordinate(kv.get("latitude") or kv.get("lat"))
    lon = parse_coordinate(kv.get("longitude") or kv.get("lon") or kv.get("long"))
    reasons: list[str] = []
    if lat is None or lon is None:
        valid = False
        reasons.append("NO_NUMERIC_COORDINATE")
    elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
        valid = False
        reasons.append("COORDINATE_OUT_OF_RANGE")
    elif lat == 0 and lon == 0:
        valid = False
        reasons.append("ZERO_ZERO_COORDINATE")
    speed_raw = kv.get("speed") or kv.get("speed-mps")
    speed = _num(speed_raw)
    if speed is not None and speed_raw and "km/h" in str(speed_raw).lower():
        speed = speed / 3.6
    if speed is not None and speed < 0:
        valid = False
        reasons.append("NEGATIVE_SPEED")
    router_time = kv.get("date-and-time") or kv.get("time") or kv.get("gps-time")
    return {
        "utc": utc,
        "router_gps_time": router_time,
        "valid": valid,
        "gps_valid": valid,
        "gps_valid_reason": ";".join(reasons) if reasons else None,
        "latitude": lat if valid else None,
        "longitude": lon if valid else None,
        "altitude_m": _num(kv.get("altitude")),
        "speed_mps": speed,
        "course_deg": _num(kv.get("course") or kv.get("bearing")),
        "satellites": _int(kv.get("satellites") or kv.get("satellites-used")),
        "hdop": _num(kv.get("hdop") or kv.get("horizontal-dilution")),
    }


def parse_band(raw: Any) -> tuple[str | None, int | None, int | None, int | None]:
    if raw is None:
        return None, None, None, None
    text = str(raw)
    bm = re.search(r"\bB?([0-9]{1,3})\b", text, re.I)
    band = f"B{bm.group(1)}" if bm else None
    width = None
    wm = re.search(r"@([0-9]+(?:\.[0-9]+)?)\s*M", text, re.I)
    if wm:
        width = int(float(wm.group(1)))
    earfcn = None
    em = re.search(r"earfcn\s*[:=]?\s*([0-9]+)", text, re.I)
    if em:
        earfcn = int(em.group(1))
    pci = None
    pm = re.search(r"(?:phy-cellid|pci)\s*[:=]?\s*([0-9]+)", text, re.I)
    if pm:
        pci = int(pm.group(1))
    return band, width, earfcn, pci


def split_ca_bands(raw: Any) -> list[str]:
    if raw is None:
        return []
    out: list[str] = []
    for match in re.finditer(r"\bB?([0-9]{1,3})\b", str(raw), re.I):
        band = f"B{match.group(1)}"
        if band not in out:
            out.append(band)
    return out


def normalize_operator(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if "elisa" in text:
        return "Elisa"
    if "telia" in text or "emt" in text:
        return "Telia"
    return str(value).strip() or None


def parse_lte_monitor(
    raw: str,
    interface: str,
    utc: str | None = None,
    session_map: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kv = parse_routeros_kv(raw)
    primary_raw = kv.get("primary-band")
    band, width, earfcn_from_band, pci_from_band = parse_band(primary_raw)
    operator_network = normalize_operator(kv.get("current-operator") or kv.get("operator"))
    mapped = (session_map or {}).get(interface, {})
    operator = operator_network or mapped.get("operator")
    operator_source = "network" if operator_network else "session_sim_map" if operator else None
    status = kv.get("status")
    registered = status is not None and "registered" in status.lower()
    return {
        "utc": utc or utc_now(),
        "interface": interface,
        "modem_id": mapped.get("modem_id"),
        "operator": operator,
        "operator_source": operator_source,
        "network_operator": operator_network,
        "sim_id": mapped.get("sim_id"),
        "status": status,
        "registered": registered,
        "primary_band": band,
        "primary_band_raw": primary_raw,
        "bandwidth_mhz": width,
        "earfcn": _int(kv.get("earfcn")) or earfcn_from_band,
        "enb_id": kv.get("enb-id"),
        "cell_id": kv.get("cell-id"),
        "sector_id": kv.get("sector-id"),
        "pci": _int(kv.get("phy-cellid")) or pci_from_band,
        "ca_bands": split_ca_bands(kv.get("ca-band")),
        "rssi_dbm": _num(kv.get("rssi")),
        "rsrp_dbm": _num(kv.get("rsrp")),
        "rsrq_db": _num(kv.get("rsrq")),
        "sinr_db": _num(kv.get("sinr")),
        "cqi": _int(kv.get("cqi")),
        "ri": _int(kv.get("ri")),
        "tx_bytes": _int((stats or {}).get("tx-byte")),
        "tx_packets": _int((stats or {}).get("tx-packet")),
        "tx_queue_drops": _int((stats or {}).get("tx-queue-drop")),
        "raw_parse": kv,
    }


def parse_ping_line(line: str, path: str, operator: str | None = None, utc: str | None = None) -> dict[str, Any] | None:
    seq = _int(re.search(r"icmp_seq=([0-9]+)", line).group(1)) if "icmp_seq=" in line else None
    tm = re.search(r"time=([0-9]+(?:\.[0-9]+)?)", line)
    if tm:
        return {
            "utc": utc or utc_now(),
            "path": path,
            "operator": operator,
            "seq": seq,
            "success": True,
            "rtt_ms": float(tm.group(1)),
        }
    if "timeout" in line.lower() or "unreachable" in line.lower():
        return {"utc": utc or utc_now(), "path": path, "operator": operator, "seq": seq, "success": False, "rtt_ms": None}
    return None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    idx = (len(values) - 1) * pct
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - idx) + values[hi] * (idx - lo)


def nearest(rows: list[dict[str, Any]], when: dt.datetime, max_age_s: float) -> tuple[dict[str, Any] | None, float | None]:
    best = None
    best_age = None
    for row in rows:
        ts = row.get("utc") or row.get("timestamp_utc")
        if not ts:
            continue
        age = abs((parse_utc(ts) - when).total_seconds())
        if best_age is None or age < best_age:
            best = row
            best_age = age
    if best_age is None or best_age > max_age_s:
        return None, best_age
    return best, best_age


def _session_bounds(streams: Iterable[list[dict[str, Any]]]) -> tuple[dt.datetime | None, dt.datetime | None]:
    stamps: list[dt.datetime] = []
    for rows in streams:
        for row in rows:
            ts = row.get("utc") or row.get("timestamp_utc") or row.get("interval_start_utc")
            if ts:
                stamps.append(parse_utc(ts))
            ts2 = row.get("interval_end_utc")
            if ts2:
                stamps.append(parse_utc(ts2))
    if not stamps:
        return None, None
    return min(stamps).replace(microsecond=0), max(stamps).replace(microsecond=0)


def ping_metrics(rows: list[dict[str, Any]], start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    subset = [r for r in rows if r.get("utc") and start <= parse_utc(r["utc"]) < end]
    successes = [float(r["rtt_ms"]) for r in subset if r.get("success") and r.get("rtt_ms") is not None]
    count = len(subset)
    return {
        "probe_count": count,
        "success_count": len(successes),
        "loss": round((count - len(successes)) / count * 100.0, 3) if count else None,
        "p50": percentile(successes, 0.50),
        "p95": percentile(successes, 0.95),
        "max": max(successes) if successes else None,
    }


def traffic_for_second(rows: list[dict[str, Any]], when: dt.datetime) -> dict[str, Any]:
    for row in rows:
        a = row.get("interval_start_utc")
        b = row.get("interval_end_utc")
        if a and b and parse_utc(a) <= when < parse_utc(b):
            return row
    return {}


def build_timeline(session_dir: Path, public_dir: Path) -> list[dict[str, Any]]:
    gps = load_jsonl(session_dir / "gps.jsonl")
    lte1 = load_jsonl(session_dir / "lte1.jsonl")
    lte2 = load_jsonl(session_dir / "lte2.jsonl")
    p1 = load_jsonl(session_dir / "ping_lte1.jsonl")
    p2 = load_jsonl(session_dir / "ping_lte2.jsonl")
    t1 = load_jsonl(session_dir / "traffic_lte1.jsonl")
    t2 = load_jsonl(session_dir / "traffic_lte2.jsonl")
    start, stop = _session_bounds([gps, lte1, lte2, p1, p2, t1, t2])
    if start is None or stop is None:
        return []
    rows: list[dict[str, Any]] = []
    cur = start
    while cur <= stop:
        gps_row, gps_age = nearest(gps, cur, GPS_STALE_S)
        row: dict[str, Any] = {
            "utc": fmt_utc(cur),
            "gps_valid": bool(gps_row and gps_row.get("valid")),
            "lat": gps_row.get("latitude") if gps_row and gps_row.get("valid") else None,
            "lon": gps_row.get("longitude") if gps_row and gps_row.get("valid") else None,
            "speed_mps": gps_row.get("speed_mps") if gps_row else None,
            "gps_age_s": round(gps_age, 3) if gps_age is not None else None,
        }
        for path, lte_rows, ping_rows, traffic_rows in (("lte1", lte1, p1, t1), ("lte2", lte2, p2, t2)):
            lte, lte_age = nearest(lte_rows, cur, LTE_STALE_S)
            pm = ping_metrics(ping_rows, cur, cur + dt.timedelta(seconds=1))
            tr = traffic_for_second(traffic_rows, cur)
            row.update(
                {
                    f"{path}_operator": lte.get("operator") if lte else None,
                    f"{path}_band": lte.get("primary_band") if lte else None,
                    f"{path}_earfcn": lte.get("earfcn") if lte else None,
                    f"{path}_cell": lte.get("cell_id") if lte else None,
                    f"{path}_pci": lte.get("pci") if lte else None,
                    f"{path}_rsrp": lte.get("rsrp_dbm") if lte else None,
                    f"{path}_rsrq": lte.get("rsrq_db") if lte else None,
                    f"{path}_sinr": lte.get("sinr_db") if lte else None,
                    f"{path}_registered": lte.get("registered") if lte else None,
                    f"{path}_sample_age_s": round(lte_age, 3) if lte_age is not None else None,
                    f"{path}_ping_p50": pm["p50"],
                    f"{path}_ping_p95": pm["p95"],
                    f"{path}_ping_max": pm["max"],
                    f"{path}_ping_loss": pm["loss"],
                    f"{path}_udp_mbps": tr.get("receiver_mbps") or tr.get("sender_mbps"),
                    f"{path}_udp_loss": tr.get("loss_percent"),
                    f"{path}_udp_loss_window_s": tr.get("udp_loss_window_s"),
                }
            )
        rows.append(row)
        cur += dt.timedelta(seconds=1)
    public_dir.mkdir(parents=True, exist_ok=True)
    write_timeline(public_dir / "timeline.csv", rows)
    with (public_dir / "timeline.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


TIMELINE_COLUMNS = [
    "utc",
    "gps_valid",
    "lat",
    "lon",
    "speed_mps",
    "gps_age_s",
    "lte1_operator",
    "lte1_band",
    "lte1_earfcn",
    "lte1_cell",
    "lte1_pci",
    "lte1_rsrp",
    "lte1_rsrq",
    "lte1_sinr",
    "lte1_registered",
    "lte1_sample_age_s",
    "lte1_ping_p50",
    "lte1_ping_p95",
    "lte1_ping_max",
    "lte1_ping_loss",
    "lte1_udp_mbps",
    "lte1_udp_loss",
    "lte1_udp_loss_window_s",
    "lte2_operator",
    "lte2_band",
    "lte2_earfcn",
    "lte2_cell",
    "lte2_pci",
    "lte2_rsrp",
    "lte2_rsrq",
    "lte2_sinr",
    "lte2_registered",
    "lte2_sample_age_s",
    "lte2_ping_p50",
    "lte2_ping_p95",
    "lte2_ping_max",
    "lte2_ping_loss",
    "lte2_udp_mbps",
    "lte2_udp_loss",
    "lte2_udp_loss_window_s",
]


def write_timeline(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TIMELINE_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def detect_lte_events(rows: list[dict[str, Any]], path: str, gps_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    last: dict[str, Any] | None = None
    gps_rows = gps_rows or []
    fields = [
        ("primary_band", "BAND_CHANGE"),
        ("earfcn", "EARFCN_CHANGE"),
        ("cell_id", "CELL_CHANGE"),
        ("ca_bands", "CA_CHANGE"),
        ("registered", "REGISTRATION"),
        ("operator", "OPERATOR_CHANGE_OR_CONFLICT"),
    ]
    for row in rows:
        if last is None:
            last = row
            continue
        for key, typ in fields:
            before = last.get(key)
            after = row.get(key)
            if before in (None, [], "") or after in (None, [], "") or before == after:
                continue
            event_type = typ
            if key == "registered":
                event_type = "REGISTRATION_RESTORED" if after else "REGISTRATION_LOST"
            gps, _age = nearest(gps_rows, parse_utc(row["utc"]), GPS_STALE_S) if gps_rows else (None, None)
            events.append(
                {
                    "utc": row.get("utc"),
                    "path": path,
                    "operator": row.get("operator") or last.get("operator"),
                    "type": event_type,
                    "before": {key: before},
                    "after": {key: after},
                    "gps": gps if gps and gps.get("valid") else None,
                }
            )
        last = row
    return events


def detect_buffering_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in ("lte1", "lte2"):
        active: dict[str, Any] | None = None
        for row in timeline:
            p95 = row.get(f"{path}_ping_p95")
            registered = row.get(f"{path}_registered")
            traffic = row.get(f"{path}_udp_mbps")
            threshold = None
            if registered and traffic is not None and p95 is not None:
                if p95 > 1000:
                    threshold = "SEVERE_BUFFERING"
                elif p95 > 300:
                    threshold = "HIGH_LATENCY_UNDER_LOAD"
            if threshold:
                if active is None:
                    active = {"type": threshold, "start": row["utc"], "rows": []}
                active["type"] = "SEVERE_BUFFERING" if threshold == "SEVERE_BUFFERING" else active["type"]
                active["rows"].append(row)
            elif active:
                if len(active["rows"]) >= 3:
                    first = active["rows"][0]
                    last = active["rows"][-1]
                    events.append(
                        {
                            "utc": active["start"],
                            "end_utc": last["utc"],
                            "path": path,
                            "operator": first.get(f"{path}_operator"),
                            "type": active["type"],
                            "offered_bitrate": "6M",
                            "measured_mbps": statistics.median(
                                [r[f"{path}_udp_mbps"] for r in active["rows"] if r.get(f"{path}_udp_mbps") is not None]
                            ),
                            "band": first.get(f"{path}_band"),
                            "cell": first.get(f"{path}_cell"),
                            "lat": first.get("lat"),
                            "lon": first.get("lon"),
                        }
                    )
                active = None
    return events


def diversity_summary(timeline: list[dict[str, Any]], strict: bool = False) -> dict[str, Any]:
    rtt_limit = 60 if strict else 100
    loss_limit = 1 if strict else 2
    counts = {"both_good": 0, "elisa_impaired_telia_good": 0, "telia_impaired_elisa_good": 0, "both_impaired": 0}
    longest_both_bad = 0
    cur_bad = 0
    for row in timeline:
        good: dict[str, bool] = {}
        for path in ("lte1", "lte2"):
            ping_loss = row.get(f"{path}_ping_loss")
            udp_loss = row.get(f"{path}_udp_loss")
            p95 = row.get(f"{path}_ping_p95")
            registered = row.get(f"{path}_registered")
            good[path] = bool(
                registered
                and p95 is not None
                and p95 < rtt_limit
                and (ping_loss is None or ping_loss < loss_limit)
                and (udp_loss is None or udp_loss < loss_limit)
            )
        if good["lte1"] and good["lte2"]:
            counts["both_good"] += 1
            cur_bad = 0
        elif not good["lte1"] and good["lte2"]:
            counts["elisa_impaired_telia_good"] += 1
            cur_bad = 0
        elif good["lte1"] and not good["lte2"]:
            counts["telia_impaired_elisa_good"] += 1
            cur_bad = 0
        else:
            counts["both_impaired"] += 1
            cur_bad += 1
            longest_both_bad = max(longest_both_bad, cur_bad)
    total = len(timeline)
    return {
        **counts,
        "longest_both_impaired_interval_s": longest_both_bad,
        "percentage_with_at_least_one_good_path": round((total - counts["both_impaired"]) / total * 100.0, 2) if total else None,
        "criteria": "strict" if strict else "normal",
    }


def write_geo_outputs(public_dir: Path, gps_rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    points = [r for r in gps_rows if r.get("valid") and r.get("latitude") is not None and r.get("longitude") is not None]
    if not points:
        return
    trkpts = "\n".join(
        f'      <trkpt lat="{p["latitude"]}" lon="{p["longitude"]}"><time>{p["utc"]}</time></trkpt>' for p in points
    )
    (public_dir / "track.gpx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="ltap-lte-testbench">\n'
        "  <trk><name>ELMO LTE drive test</name><trkseg>\n"
        f"{trkpts}\n"
        "  </trkseg></trk>\n</gpx>\n",
        encoding="utf-8",
    )
    (public_dir / "track.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"utc": p["utc"]},
                        "geometry": {"type": "Point", "coordinates": [p["longitude"], p["latitude"]]},
                    }
                    for p in points
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    event_features = []
    for e in events:
        gps = e.get("gps") or {}
        if gps.get("latitude") is not None and gps.get("longitude") is not None:
            event_features.append(
                {
                    "type": "Feature",
                    "properties": {k: v for k, v in e.items() if k != "gps"},
                    "geometry": {"type": "Point", "coordinates": [gps["longitude"], gps["latitude"]]},
                }
            )
    (public_dir / "events.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": event_features}, indent=2) + "\n",
        encoding="utf-8",
    )
    with (public_dir / "hotspots.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["lat_bin", "lon_bin", "event_count"], lineterminator="\n")
        writer.writeheader()
        bins: dict[tuple[float, float], int] = {}
        for e in event_features:
            lon, lat = e["geometry"]["coordinates"]
            key = (round(lat, 3), round(lon, 3))
            bins[key] = bins.get(key, 0) + 1
        for (lat, lon), count in sorted(bins.items()):
            writer.writerow({"lat_bin": lat, "lon_bin": lon, "event_count": count})


def analyze_session(runtime_dir: Path, public_dir: Path) -> dict[str, Any]:
    public_dir.mkdir(parents=True, exist_ok=True)
    state = {}
    if (runtime_dir / "STATE.json").exists():
        state = json.loads((runtime_dir / "STATE.json").read_text(encoding="utf-8"))
    legacy = not (runtime_dir / "lte1.jsonl").exists() and (public_dir / "timeline.csv").exists()
    if legacy:
        existing_summary = {}
        summary_path = public_dir / "summary.json"
        if summary_path.exists():
            try:
                existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing_summary = {}
        summary = {
            **existing_summary,
            "skill": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "resolution": "LEGACY_COARSE_EPOCH_DATA",
            "session_id": runtime_dir.name,
            "gps_valid_fixes": existing_summary.get("gps_valid_fixes", 0),
            "note": "Old run preserved; continuous GPS/LTE/ping streams were not collected.",
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        report = public_dir / "REPORT.md"
        existing = report.read_text(encoding="utf-8") if report.exists() else ""
        legacy_note = (
            "# ELMO LTE Drive Test Report\n\n"
            "Resolution: `LEGACY_COARSE_EPOCH_DATA`\n\n"
            "This session predates v2 continuous collectors. The analyzer did not fabricate GPS, LTE, or ping samples.\n\n"
        )
        if "Resolution: `LEGACY_COARSE_EPOCH_DATA`" not in existing:
            report.write_text(legacy_note + existing, encoding="utf-8")
        return summary
    timeline = build_timeline(runtime_dir, public_dir)
    gps_rows = load_jsonl(runtime_dir / "gps.jsonl")
    events = []
    events.extend(detect_lte_events(load_jsonl(runtime_dir / "lte1.jsonl"), "lte1", gps_rows))
    events.extend(detect_lte_events(load_jsonl(runtime_dir / "lte2.jsonl"), "lte2", gps_rows))
    events.extend(detect_buffering_events(timeline))
    with (public_dir / "events.json").open("w", encoding="utf-8") as fh:
        json.dump(events, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with (public_dir / "events.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["utc", "end_utc", "path", "operator", "type"], lineterminator="\n")
        writer.writeheader()
        for e in events:
            writer.writerow({k: e.get(k) for k in writer.fieldnames or []})
    write_geo_outputs(public_dir, gps_rows, events)
    div_normal = diversity_summary(timeline, strict=False)
    div_strict = diversity_summary(timeline, strict=True)
    gps_valid = len([r for r in gps_rows if r.get("valid")])
    summary = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "resolution": "V2_CONTINUOUS_TIMELINE",
        "session_id": state.get("session_id") or runtime_dir.name,
        "timeline_rows": len(timeline),
        "gps_valid_fixes": gps_valid,
        "lte1_samples": len(load_jsonl(runtime_dir / "lte1.jsonl")),
        "lte2_samples": len(load_jsonl(runtime_dir / "lte2.jsonl")),
        "ping_lte1_samples": len(load_jsonl(runtime_dir / "ping_lte1.jsonl")),
        "ping_lte2_samples": len(load_jsonl(runtime_dir / "ping_lte2.jsonl")),
        "traffic_loss_resolution_s": state.get("traffic_loss_resolution_s"),
        "diversity_normal": div_normal,
        "diversity_strict": div_strict,
    }
    (public_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (public_dir / "diversity.csv").write_text(
        "criteria,both_good,elisa_impaired_telia_good,telia_impaired_elisa_good,both_impaired,longest_both_impaired_interval_s,percentage_with_at_least_one_good_path\n"
        + "\n".join(
            ",".join(str(d.get(k)) for k in ["criteria", "both_good", "elisa_impaired_telia_good", "telia_impaired_elisa_good", "both_impaired", "longest_both_impaired_interval_s", "percentage_with_at_least_one_good_path"])
            for d in (div_normal, div_strict)
        )
        + "\n",
        encoding="utf-8",
    )
    for name in ("handovers.csv", "band_summary.csv", "cell_summary.csv"):
        (public_dir / name).write_text("type,path,operator,count\n", encoding="utf-8")
    (public_dir / "REPORT.md").write_text(
        f"# ELMO LTE Drive Test Report\n\n"
        f"Skill: `{SKILL_NAME}` `{SKILL_VERSION}`\n\n"
        f"Resolution: `V2_CONTINUOUS_TIMELINE`\n\n"
        f"Timeline rows: {len(timeline)}\n\n"
        f"GPS valid fixes: {gps_valid}\n\n"
        f"LTE samples: lte1={summary['lte1_samples']}, lte2={summary['lte2_samples']}\n\n"
        f"Ping samples: lte1={summary['ping_lte1_samples']}, lte2={summary['ping_lte2_samples']}\n\n"
        f"Normal diversity: {json.dumps(div_normal, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    return summary


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def synthetic_verification() -> list[Check]:
    checks: list[Check] = []
    gps = parse_routeros_gps("valid: yes\nlatitude: 59.123456\nlongitude: 24.123456\nspeed: 0.1\n", "2026-08-12T00:00:00+00:00")
    checks.append(Check("GPS parser valid decimal coordinate", gps["valid"] and gps["latitude"] == 59.123456, str(gps)))
    gps2 = parse_routeros_gps("valid: no\n", "2026-08-12T00:00:01+00:00")
    checks.append(Check("GPS parser invalid/no-fix output", not gps2["valid"] and gps2["latitude"] is None, str(gps2)))
    gps3 = parse_routeros_gps('valid: yes\nlatitude: "59 7 24.4416 N"\nlongitude: "24 7 24.4416 E"\n', "2026-08-12T00:00:02+00:00")
    checks.append(Check("GPS parser alternate DMS formatting", gps3["valid"], str(gps3)))
    gps4 = parse_routeros_gps("valid: yes\nlatitude: 5922.0159\nlongitude: 02455.2192\nspeed: 7.2 km/h\n", "2026-08-12T00:00:03+00:00")
    checks.append(Check("GPS parser RouterOS compact ddmm.mmmm formatting", gps4["valid"] and round(gps4["latitude"], 6) == 59.366932, str(gps4)))
    for band in ("B1@10Mhz earfcn: 300 phy-cellid: 11", "B3@15Mhz earfcn: 1875 phy-cellid: 69", "B7", "B20", "B38"):
        lte = parse_lte_monitor(f"status: registered\ncurrent-operator: Elisa EE\nprimary-band: {band}\nrsrp: -95dBm\n", "lte1")
        checks.append(Check(f"LTE parser {band.split('@')[0]}", lte["primary_band"] is not None and lte["operator"] == "Elisa", str(lte)))
    lte_down = parse_lte_monitor("status: searching\n", "lte1")
    checks.append(Check("LTE parser deregistered state", not lte_down["registered"], str(lte_down)))
    rows = [
        parse_lte_monitor("status: registered\nprimary-band: B3\ncell-id: A\n", "lte1", "2026-08-12T00:00:00+00:00"),
        parse_lte_monitor("status: registered\nprimary-band: B20\ncell-id: A\n", "lte1", "2026-08-12T00:00:01+00:00"),
        parse_lte_monitor("status: registered\nprimary-band: B20\ncell-id: B\n", "lte1", "2026-08-12T00:00:02+00:00"),
        parse_lte_monitor("status: searching\nprimary-band: B20\ncell-id: B\n", "lte1", "2026-08-12T00:00:03+00:00"),
        parse_lte_monitor("status: registered\nprimary-band: B20\ncell-id: B\n", "lte1", "2026-08-12T00:00:04+00:00"),
    ]
    events = detect_lte_events(rows, "lte1")
    types = [e["type"] for e in events]
    checks.append(Check("Event detector B3 -> B20", "BAND_CHANGE" in types, str(types)))
    checks.append(Check("Event detector cell A -> B", "CELL_CHANGE" in types, str(types)))
    checks.append(Check("Event detector registration loss/recovery", "REGISTRATION_LOST" in types and "REGISTRATION_RESTORED" in types, str(types)))
    sample, age = nearest([{"utc": "2026-08-12T00:00:00+00:00", "v": 1}], parse_utc("2026-08-12T00:00:01+00:00"), 2)
    stale, _ = nearest([{"utc": "2026-08-12T00:00:00+00:00", "v": 1}], parse_utc("2026-08-12T00:00:03+00:00"), 2)
    checks.append(Check("Timeline nearest sample selection", sample is not None and age == 1, str((sample, age))))
    checks.append(Check("Timeline stale-data cutoff", stale is None, str(stale)))
    timeline = []
    for i, pair in enumerate([(50, 50), (150, 50), (50, 150), (150, 150)]):
        timeline.append({"utc": f"2026-08-12T00:00:0{i}+00:00", "lte1_registered": True, "lte2_registered": True, "lte1_ping_p95": pair[0], "lte2_ping_p95": pair[1], "lte1_ping_loss": 0, "lte2_ping_loss": 0})
    div = diversity_summary(timeline)
    checks.append(Check("Diversity analyzer all categories", all(div[k] == 1 for k in ("both_good", "elisa_impaired_telia_good", "telia_impaired_elisa_good", "both_impaired")), str(div)))
    return checks


def write_verification_report(path: Path, checks: list[Check], live: dict[str, Any] | None = None) -> str:
    critical_pass = all(c.passed for c in checks) and (live or {}).get("critical_pass", False)
    classification = "PASS_DRIVE_SKILL_V2" if critical_pass else (live or {}).get("blocker") or "FAIL_DRIVE_SKILL_V2"
    lines = [
        "# Drive Skill v2 Verification",
        "",
        f"Classification: `{classification}`",
        "",
        "## Stage A - Parser/Unit Tests",
        "",
    ]
    for c in checks:
        lines.append(f"- {'PASS' if c.passed else 'FAIL'} - {c.name}: {c.detail}")
    if live is not None:
        lines += ["", "## Stage B - Live/Stationary Validation", "", "```json", json.dumps(live, indent=2), "```"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return classification
