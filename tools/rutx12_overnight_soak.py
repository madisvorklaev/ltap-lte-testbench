#!/usr/bin/env python3
"""Detached overnight soak runner for RB4011 + two RUTX12 uplink tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[1]
BASE = REPO / "runtime" / "rutx12-rb4011"
SERVER = "217.18.95.142"
SOURCE_A = "192.168.101.201"
SOURCE_B = "192.168.101.202"
RB_HOST = "admin@192.168.88.1"
RUT_A = "root@192.168.11.1"
RUT_B = "root@192.168.12.1"
SSH_KEY = pathlib.Path.home() / ".ssh" / "elmo_openclaw_ed25519"
PORT_PAIRS = [("5201", "5202"), ("5203", "5204"), ("5205", "5206"), ("5207", "5208")]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_dir_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-overnight-auto-dual5m-soak")


def ssh_base(host: str, timeout: int = 8) -> list[str]:
    return [
        "ssh",
        "-i",
        str(SSH_KEY),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={timeout}",
        host,
    ]


def cmd_run(argv: list[str], timeout: int | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return {
            "argv": argv,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": time.monotonic() - started,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration_s": time.monotonic() - started,
            "timeout": True,
        }


def write_json(path: pathlib.Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def append_jsonl(path: pathlib.Path, value: Any) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def iperf_json_valid(path: pathlib.Path) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if data.get("error"):
        return False, str(data["error"])
    if not (data.get("end") or {}).get("sum_received"):
        return False, "missing sum_received"
    return True, "ok"


def start_iperf(path: pathlib.Path, source: str, port: str, seconds: int, rate: str) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        [
            "iperf3",
            "-4",
            "-c",
            SERVER,
            "-p",
            port,
            "-B",
            source,
            "-u",
            "-b",
            rate,
            "-l",
            "1200",
            "-t",
            str(seconds),
            "-i",
            "1",
            "-J",
        ],
        stdout=(path / "iperf.json").open("w"),
        stderr=(path / "iperf.stderr").open("w"),
        text=True,
    )


def choose_ports(run_dir: pathlib.Path, epoch_id: int) -> tuple[str, str] | None:
    port_dir = run_dir / "portchecks" / f"epoch-{epoch_id:04d}"
    port_dir.mkdir(parents=True, exist_ok=True)
    for port_a, port_b in PORT_PAIRS:
        a_dir = port_dir / f"a-{port_a}"
        b_dir = port_dir / f"b-{port_b}"
        a_dir.mkdir()
        b_dir.mkdir()
        pa = start_iperf(a_dir, SOURCE_A, port_a, 3, "1000000")
        pb = start_iperf(b_dir, SOURCE_B, port_b, 3, "1000000")
        for proc in (pa, pb):
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        ok_a, msg_a = iperf_json_valid(a_dir / "iperf.json")
        ok_b, msg_b = iperf_json_valid(b_dir / "iperf.json")
        append_jsonl(
            run_dir / "events.jsonl",
            {
                "utc": utc_now(),
                "type": "PORT_CHECK",
                "epoch": epoch_id,
                "ports": {"a": port_a, "b": port_b},
                "ok": ok_a and ok_b,
                "messages": {"a": msg_a, "b": msg_b},
            },
        )
        if ok_a and ok_b:
            return port_a, port_b
        time.sleep(5)
    return None


def start_ping(run_dir: pathlib.Path, source: str, label: str) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        ["ping", "-O", "-D", "-i", "0.2", "-W", "1", "-I", source, SERVER],
        stdout=(run_dir / f"ping-{label}.txt").open("w"),
        stderr=(run_dir / f"ping-{label}.stderr").open("w"),
        text=True,
    )


def sample_router(run_dir: pathlib.Path) -> None:
    result = cmd_run(
        ssh_base(RB_HOST)
        + [
            '/queue tree print stats detail; /ip firewall mangle print stats detail where comment~"ELMO|RUTX"; '
            '/interface ethernet print stats detail where name~"ether2|ether3"; /system resource print'
        ],
        timeout=10,
    )
    append_jsonl(run_dir / "rb4011-samples.jsonl", {"utc": utc_now(), **result})


def sample_rut(run_dir: pathlib.Path, host: str, label: str) -> None:
    result = cmd_run(ssh_base(host, timeout=5) + ["gsmctl -O 3-1 -q 2>/dev/null || true"], timeout=8)
    append_jsonl(run_dir / f"rut-{label}-samples.jsonl", {"utc": utc_now(), **result})


def parse_iperf(path: pathlib.Path) -> dict[str, Any]:
    ok, msg = iperf_json_valid(path)
    if not ok:
        return {"valid": False, "error": msg}
    data = json.loads(path.read_text())
    recv = data["end"]["sum_received"]
    sent = (data.get("end") or {}).get("sum_sent") or {}
    return {
        "valid": True,
        "receiver_mbps": recv.get("bits_per_second", 0) / 1_000_000,
        "lost_percent": recv.get("lost_percent"),
        "lost_packets": recv.get("lost_packets"),
        "packets": recv.get("packets"),
        "jitter_ms": recv.get("jitter_ms"),
        "sender_mbps": sent.get("bits_per_second", 0) / 1_000_000,
    }


def ping_summary(path: pathlib.Path) -> dict[str, Any]:
    text = path.read_text(errors="ignore") if path.exists() else ""
    values = [float(match) for match in re.findall(r"time=([0-9.]+)", text)]
    stats = re.search(r"(\d+) packets transmitted, (\d+) received,.*?(\d+(?:\.\d+)?)% packet loss", text, re.S)

    def percentile(pct: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        idx = (len(ordered) - 1) * pct / 100
        lo = int(idx)
        hi = min(lo + 1, len(ordered) - 1)
        frac = idx - lo
        return round(ordered[lo] * (1 - frac) + ordered[hi] * frac, 1)

    return {
        "samples": len(values),
        "sent": int(stats.group(1)) if stats else None,
        "received": int(stats.group(2)) if stats else len(values),
        "loss_percent": float(stats.group(3)) if stats else None,
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "p99_ms": percentile(99),
        "max_ms": max(values) if values else None,
    }


def summarize(run_dir: pathlib.Path) -> dict[str, Any]:
    epochs: list[dict[str, Any]] = []
    for epoch_dir in sorted((run_dir / "epochs").glob("epoch-*")):
        epochs.append(
            {
                "epoch": epoch_dir.name,
                "a": parse_iperf(epoch_dir / "a" / "iperf.json"),
                "b": parse_iperf(epoch_dir / "b" / "iperf.json"),
            }
        )
    valid_epochs = [epoch for epoch in epochs if epoch["a"].get("valid") and epoch["b"].get("valid")]
    summary = {
        "session": run_dir.name,
        "updated_utc": utc_now(),
        "epochs_total": len(epochs),
        "epochs_valid_dual": len(valid_epochs),
        "ping": {"a": ping_summary(run_dir / "ping-a.txt"), "b": ping_summary(run_dir / "ping-b.txt")},
        "recent_epochs": epochs[-5:],
    }
    write_json(run_dir / "summary.json", summary)
    return summary


def write_checksums(run_dir: pathlib.Path) -> None:
    lines = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run_dir)}")
    (run_dir / "checksums.sha256").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--epoch-seconds", type=int, default=300)
    parser.add_argument("--rate", default="5000000")
    args = parser.parse_args()

    run_dir = BASE / run_dir_name()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "epochs").mkdir()
    (run_dir / "portchecks").mkdir()
    end_monotonic = time.monotonic() + args.hours * 3600
    end_utc = datetime.now(timezone.utc) + timedelta(hours=args.hours)
    stop = False

    def handle_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    write_json(
        run_dir / "manifest.json",
        {
            "session": run_dir.name,
            "started_utc": utc_now(),
            "planned_end_utc": end_utc.isoformat(timespec="seconds"),
            "topology": "rb4011_two_rutx12",
            "treatment": "auto_unshaped_overnight_dual5m_soak",
            "server_ipv4": SERVER,
            "source_a": SOURCE_A,
            "source_b": SOURCE_B,
            "rate": args.rate,
            "udp_payload": 1200,
            "epoch_seconds": args.epoch_seconds,
            "stop_file": str(run_dir / "STOP"),
        },
    )
    write_json(run_dir / "STATE.json", {"state": "STARTING", "updated_utc": utc_now(), "run_dir": str(run_dir)})

    for name, command in {
        "host-routes.txt": ["bash", "-lc", "ip -br addr show eno1; ip route get 217.18.95.142 from 192.168.101.201; ip route get 217.18.95.142 from 192.168.101.202"],
        "rb-before.txt": ssh_base(RB_HOST) + ['/export hide-sensitive; /queue tree print detail; /ip firewall mangle print stats detail where comment~"ELMO|RUTX"; /ip route print detail where comment~"ELMO"; /routing rule print detail where comment~"ELMO"'],
        "rut-a-before.txt": ssh_base(RUT_A, timeout=5) + ["gsmctl -O 3-1 -q 2>/dev/null || true"],
        "rut-b-before.txt": ssh_base(RUT_B, timeout=5) + ["gsmctl -O 3-1 -q 2>/dev/null || true"],
    }.items():
        result = cmd_run(command, timeout=12)
        (run_dir / name).write_text(json.dumps(result, indent=2) + "\n")

    ping_a = start_ping(run_dir, SOURCE_A, "a")
    ping_b = start_ping(run_dir, SOURCE_B, "b")
    write_json(run_dir / "STATE.json", {"state": "RUNNING", "updated_utc": utc_now(), "run_dir": str(run_dir)})

    epoch_id = 0
    last_rb = 0.0
    last_rut = 0.0
    try:
        while not stop and time.monotonic() < end_monotonic and not (run_dir / "STOP").exists():
            epoch_id += 1
            ports = choose_ports(run_dir, epoch_id)
            if ports is None:
                append_jsonl(run_dir / "events.jsonl", {"utc": utc_now(), "type": "NO_RECEIVER_PORTS", "epoch": epoch_id})
                time.sleep(60)
                continue
            port_a, port_b = ports
            epoch_dir = run_dir / "epochs" / f"epoch-{epoch_id:04d}"
            a_dir = epoch_dir / "a"
            b_dir = epoch_dir / "b"
            a_dir.mkdir(parents=True)
            b_dir.mkdir(parents=True)
            write_json(epoch_dir / "definition.json", {"ports": {"a": port_a, "b": port_b}, "started_utc": utc_now()})
            proc_a = start_iperf(a_dir, SOURCE_A, port_a, args.epoch_seconds, args.rate)
            proc_b = start_iperf(b_dir, SOURCE_B, port_b, args.epoch_seconds, args.rate)
            epoch_deadline = time.monotonic() + args.epoch_seconds + 45
            while time.monotonic() < epoch_deadline and (proc_a.poll() is None or proc_b.poll() is None):
                now = time.monotonic()
                if now - last_rb >= 10:
                    sample_router(run_dir)
                    last_rb = now
                if now - last_rut >= 30:
                    sample_rut(run_dir, RUT_A, "a")
                    sample_rut(run_dir, RUT_B, "b")
                    last_rut = now
                write_json(
                    run_dir / "HEARTBEAT.json",
                    {
                        "state": "RUNNING",
                        "updated_utc": utc_now(),
                        "epoch": epoch_id,
                        "run_dir": str(run_dir),
                        "stop_file": str(run_dir / "STOP"),
                    },
                )
                if stop or (run_dir / "STOP").exists() or time.monotonic() >= end_monotonic:
                    break
                time.sleep(2)
            for proc in (proc_a, proc_b):
                if proc.poll() is None:
                    proc.kill()
            proc_a.wait(timeout=5)
            proc_b.wait(timeout=5)
            (a_dir / "iperf.rc").write_text(str(proc_a.returncode) + "\n")
            (b_dir / "iperf.rc").write_text(str(proc_b.returncode) + "\n")
            write_json(epoch_dir / "finished.json", {"finished_utc": utc_now()})
            summarize(run_dir)
    finally:
        for proc in (ping_a, ping_b):
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        time.sleep(1)
        for proc in (ping_a, ping_b):
            if proc.poll() is None:
                proc.kill()
        for name, command in {
            "rb-after.txt": ssh_base(RB_HOST) + ['/queue tree print detail; /ip firewall mangle print stats detail where comment~"ELMO|RUTX"; /system resource print'],
            "rut-a-after.txt": ssh_base(RUT_A, timeout=5) + ["gsmctl -O 3-1 -q 2>/dev/null || true"],
            "rut-b-after.txt": ssh_base(RUT_B, timeout=5) + ["gsmctl -O 3-1 -q 2>/dev/null || true"],
        }.items():
            result = cmd_run(command, timeout=12)
            (run_dir / name).write_text(json.dumps(result, indent=2) + "\n")
        summary = summarize(run_dir)
        write_checksums(run_dir)
        write_json(
            run_dir / "STATE.json",
            {
                "state": "COMPLETE" if time.monotonic() >= end_monotonic else "STOPPED",
                "updated_utc": utc_now(),
                "run_dir": str(run_dir),
                "summary": summary,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
