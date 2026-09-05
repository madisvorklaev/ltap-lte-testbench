#!/usr/bin/env python3
"""Durable ELMO LTE drive-test v2 worker and CLI."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ltap_testbench.drive_tests.v2 import (  # noqa: E402
    SKILL_NAME,
    SKILL_VERSION,
    analyze_session,
    append_jsonl,
    parse_lte_monitor,
    parse_ping_line,
    parse_routeros_gps,
    parse_routeros_kv,
    utc_now,
)

CONFIG = REPO / "references/public-iperf-kit/config.json"
CAMPAIGN = REPO / "references/public-iperf-kit/campaign.json"
ROOT = REPO / "runtime/drive-tests"
PUBLIC_ROOT = REPO / "results-public/drive-tests"
ACTIVE = ROOT / "ACTIVE_SESSION.json"
DEFAULT_EPOCH_S = 10


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", text.strip().lower())
    return s.strip("-") or "auto-dual-6m"


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


class RouterSSH:
    def __init__(self, cfg: dict[str, Any]):
        self.host = cfg["host"]
        self.user = cfg.get("user", "admin")
        self.port = int(cfg.get("port", 22))
        self.key = os.path.expanduser(cfg.get("ssh_key", "~/.ssh/ltap_test_ed25519"))
        self.control_path = f"/tmp/ltap-drive-v2-{os.getpid()}-%C"

    def base(self) -> list[str]:
        return [
            "ssh",
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=2",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPersist=30",
            "-o",
            f"ControlPath={self.control_path}",
            "-i",
            self.key,
            f"{self.user}@{self.host}",
        ]

    def call(self, command: str, timeout: float = 8) -> subprocess.CompletedProcess[str]:
        return run(self.base() + [command], timeout=timeout)

    def close(self) -> None:
        run(["ssh", "-O", "exit", "-o", f"ControlPath={self.control_path}", f"{self.user}@{self.host}"], timeout=2)


def cfg() -> dict[str, Any]:
    return load_json(CONFIG, {})


def campaign() -> dict[str, Any]:
    return load_json(CAMPAIGN, {})


def command_ok(name: str) -> bool:
    return shutil.which(name) is not None


def iperf_capabilities() -> dict[str, Any]:
    if not command_ok("iperf3"):
        return {"available": False}
    ver = run(["iperf3", "--version"], timeout=5)
    help_cp = run(["iperf3", "--help"], timeout=5)
    text = help_cp.stdout + help_cp.stderr
    return {
        "available": True,
        "version": (ver.stdout or ver.stderr).splitlines()[0] if (ver.stdout or ver.stderr).splitlines() else "unknown",
        "json_stream_supported": "--json-stream" in text,
        "forceflush_supported": "--forceflush" in text,
    }


def preflight(config: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name in ("ssh", "iperf3", "ping", "ip", "python3"):
        if not command_ok(name):
            problems.append(f"missing command: {name}")
    for path_name, path_cfg in config.get("paths", {}).items():
        source = path_cfg["source_ip"]
        cp = run(["ip", "route", "get", "1.1.1.1", "from", source], timeout=5)
        if cp.returncode != 0 or config.get("router", {}).get("host", "192.168.101.254") not in cp.stdout:
            problems.append(f"source route problem for {path_name}/{source}: {cp.stdout.strip()} {cp.stderr.strip()}")
    router = RouterSSH(config["router"])
    cp = router.call("/system/resource/print", timeout=8)
    if cp.returncode != 0:
        problems.append(f"router ssh failed: {cp.stderr.strip()}")
    router.close()
    return problems


def collect_baseline(router: RouterSSH, session_dir: Path) -> dict[str, Any]:
    baseline = session_dir / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    commands = {
        "resource": "/system/resource/print",
        "routerboard": "/system/routerboard/print",
        "lte_detail": "/interface/lte/print detail without-paging",
        "lte1_monitor": "/interface/lte/monitor lte1 once",
        "lte2_monitor": "/interface/lte/monitor lte2 once",
        "packages": "/system/package/print",
        "ports": "/port/print detail",
        "gps": "/system/gps/print",
        "gps_monitor": "/system/gps/monitor once",
    }
    out: dict[str, Any] = {}
    for name, command in commands.items():
        started = utc_now()
        cp = router.call(command, timeout=10)
        completed = utc_now()
        (baseline / f"{name}.txt").write_text(cp.stdout, encoding="utf-8")
        if cp.stderr:
            (baseline / f"{name}.stderr.txt").write_text(cp.stderr, encoding="utf-8")
        out[name] = {"rc": cp.returncode, "sample_started_utc": started, "sample_completed_utc": completed, "parsed": parse_routeros_kv(cp.stdout)}
    return out


def identify_session_map(baseline: dict[str, Any]) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for iface, pseudomod in (("lte1", "LTE7-A"), ("lte2", "LTE7-B")):
        parsed = baseline.get(f"{iface}_monitor", {}).get("parsed", {})
        operator = parsed.get("current-operator") or parsed.get("operator")
        if operator:
            op = "Elisa" if "elisa" in operator.lower() else "Telia" if "telia" in operator.lower() or "emt" in operator.lower() else operator
        else:
            op = "Elisa" if iface == "lte1" else "Telia"
        sim_id = "SIM-ELISA" if op == "Elisa" else "SIM-TELIA" if op == "Telia" else f"SIM-{iface.upper()}"
        mapping[iface] = {"interface": iface, "modem_id": pseudomod, "sim_id": sim_id, "operator": op}
    return mapping


def gps_loop(router: RouterSSH, session_dir: Path, stop: threading.Event) -> None:
    while not stop.is_set():
        started = utc_now()
        try:
            cp = router.call("/system/gps/monitor once", timeout=8)
            completed = utc_now()
            append_jsonl(session_dir / "gps_raw.jsonl", {"sample_started_utc": started, "sample_completed_utc": completed, "rc": cp.returncode, "raw": cp.stdout, "stderr": cp.stderr.strip() or None})
            append_jsonl(session_dir / "gps.jsonl", parse_routeros_gps(cp.stdout, completed))
        except Exception as exc:
            append_jsonl(session_dir / "gps_raw.jsonl", {"sample_started_utc": started, "sample_completed_utc": utc_now(), "error": repr(exc), "raw": ""})
            append_jsonl(session_dir / "gps.jsonl", {"utc": utc_now(), "valid": False, "latitude": None, "longitude": None, "error": repr(exc)})
        stop.wait(1.0)


def parse_stats(raw: str) -> dict[str, int]:
    compact = " ".join(raw.splitlines())
    out: dict[str, int] = {}
    for key in ("tx-byte", "tx-packet", "tx-queue-drop", "rx-byte", "rx-packet"):
        m = re.search(rf"(?:^|\s){re.escape(key)}=([0-9 ]+)", compact)
        if m:
            out[key] = int(m.group(1).replace(" ", ""))
    return out


def lte_loop(router: RouterSSH, session_dir: Path, interface: str, mapping: dict[str, Any], stop: threading.Event) -> None:
    while not stop.is_set():
        started = utc_now()
        try:
            mon = router.call(f"/interface/lte/monitor {interface} once", timeout=7)
            stats_cp = router.call(f'/interface/print stats-detail where name="{interface}"', timeout=7)
            completed = utc_now()
            row = parse_lte_monitor(mon.stdout, interface, completed, mapping, parse_stats(stats_cp.stdout))
            row.update({"sample_started_utc": started, "sample_completed_utc": completed, "rc": mon.returncode, "raw_error": mon.stderr.strip() or None})
            if mon.returncode != 0:
                row["sample_error"] = mon.stderr.strip() or "monitor failed"
            append_jsonl(session_dir / f"{interface}.jsonl", row)
        except Exception as exc:
            append_jsonl(session_dir / f"{interface}.jsonl", {"utc": utc_now(), "interface": interface, "sample_started_utc": started, "sample_error": repr(exc)})
        stop.wait(1.0)


def ping_loop(session_dir: Path, path_name: str, source_ip: str, operator: str | None, target: str, stop: threading.Event) -> None:
    cmd = ["ping", "-n", "-D", "-O", "-I", source_ip, "-i", "0.5", target]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "PING_STARTED", "path": path_name, "pid": proc.pid, "command": cmd})
    try:
        assert proc.stdout is not None
        while not stop.is_set():
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            row = parse_ping_line(line, path_name, operator, utc_now())
            if row:
                append_jsonl(session_dir / f"ping_{path_name}.jsonl", row)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "PING_STOPPED", "path": path_name, "rc": proc.returncode})


def choose_ports(camp: dict[str, Any]) -> dict[str, int]:
    ports = list(camp.get("ports") or [5201, 5202])
    return {"lte1": int(ports[0]), "lte2": int(ports[1] if len(ports) > 1 else ports[0])}


def parse_iperf_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": repr(exc)}
    intervals = data.get("intervals") or []
    end = data.get("end") or {}
    sender = (end.get("sum_sent") or end.get("sum") or {})
    receiver = end.get("sum_received")
    if not isinstance(receiver, dict):
        return {
            "error": "missing receiver UDP summary",
            "sender_mbps": (sender.get("bits_per_second") or 0) / 1e6 if sender else None,
            "receiver_mbps": None,
            "lost_packets": None,
            "total_packets": None,
            "loss_percent": None,
            "jitter_ms": None,
            "interval_count": len(intervals),
        }
    return {
        "sender_mbps": (sender.get("bits_per_second") or 0) / 1e6 if sender else None,
        "receiver_mbps": (receiver.get("bits_per_second") or 0) / 1e6 if receiver else None,
        "lost_packets": receiver.get("lost_packets") if receiver else None,
        "total_packets": receiver.get("packets") if receiver else None,
        "loss_percent": receiver.get("lost_percent") if receiver else None,
        "jitter_ms": receiver.get("jitter_ms") if receiver else None,
        "interval_count": len(intervals),
    }


def traffic_epoch(
    session_dir: Path,
    state: dict[str, Any],
    path_name: str,
    source_ip: str,
    port: int,
    duration: int,
    partial: bool,
    stop: threading.Event,
) -> None:
    camp = campaign()
    server = camp.get("server_ipv4") or camp.get("server_hostname")
    epoch = state["current_epoch"]
    raw_dir = session_dir / "traffic_epochs" / f"epoch-{epoch:04d}-{path_name}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "iperf.json"
    err_path = raw_dir / "iperf.stderr.txt"
    cmd = [
        "iperf3",
        "-c",
        str(server),
        "-p",
        str(port),
        "-4",
        "-B",
        source_ip,
        "-u",
        "-b",
        "6M",
        "-l",
        "1200",
        "-t",
        str(duration),
        "-i",
        "1",
        "-J",
    ]
    started = utc_now()
    stop_file = session_dir / "STOP_REQUESTED"
    with out_path.open("w", encoding="utf-8") as out, err_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err, text=True)
        while proc.poll() is None and not stop.is_set() and not stop_file.exists():
            time.sleep(0.2)
        if (stop.is_set() or stop_file.exists()) and proc.poll() is None:
            partial = True
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
    completed = utc_now()
    summary = parse_iperf_summary(out_path)
    row = {
        "utc": completed,
        "path": path_name,
        "operator": state.get("session_map", {}).get(path_name, {}).get("operator"),
        "epoch": epoch,
        "interval_start_utc": started,
        "interval_end_utc": completed,
        "target_rate": "6M",
        "udp_loss_window_s": duration,
        "partial": partial,
        "partial_reason": "PARTIAL_STOPPED_BY_USER" if partial else None,
        "raw_path": str(out_path.relative_to(session_dir)),
        **summary,
    }
    append_jsonl(session_dir / f"traffic_{path_name}.jsonl", row)


def traffic_loop(session_dir: Path, state: dict[str, Any], stop: threading.Event) -> None:
    config = cfg()
    ports = choose_ports(campaign())
    duration = int(state.get("epoch_duration_s") or DEFAULT_EPOCH_S)
    while not stop.is_set() and not (session_dir / "STOP_REQUESTED").exists():
        state["current_epoch"] += 1
        atomic_json(session_dir / "STATE.json", state)
        threads = []
        for path_name, path_cfg in config["paths"].items():
            th = threading.Thread(target=traffic_epoch, args=(session_dir, state, path_name, path_cfg["source_ip"], ports[path_name], duration, False, stop))
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
    state["traffic_stopped_utc"] = utc_now()


def latest_sample(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}


def write_status(session_dir: Path, public_dir: Path, state: dict[str, Any]) -> None:
    gps = latest_sample(session_dir / "gps.jsonl")
    l1 = latest_sample(session_dir / "lte1.jsonl")
    l2 = latest_sample(session_dir / "lte2.jsonl")
    status = [
        f"Session: {state['session_id']}",
        f"Elapsed: {elapsed_s(state)} s",
        f"State: {state['state']}",
        f"GPS: {'VALID' if gps.get('valid') else 'GPS STALE' if not gps else 'SEARCHING'}, last={gps.get('utc')}",
        "Position logging: 1.0 Hz",
        "",
        f"Elisa / LTE1" if l1.get("operator") == "Elisa" else f"{l1.get('operator') or 'LTE1'} / LTE1",
        f"Band/cell: {l1.get('primary_band')} / {l1.get('cell_id')}",
        f"Traffic: {'active' if state.get('state') == 'RUNNING' else 'stopped'}",
        "",
        f"Telia / LTE2" if l2.get("operator") == "Telia" else f"{l2.get('operator') or 'LTE2'} / LTE2",
        f"Band/cell: {l2.get('primary_band')} / {l2.get('cell_id')}",
        f"Traffic: {'active' if state.get('state') == 'RUNNING' else 'stopped'}",
    ]
    public_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / "STATUS.md").write_text("\n".join(status) + "\n", encoding="utf-8")


def elapsed_s(state: dict[str, Any]) -> int:
    try:
        start = dt.datetime.fromisoformat(state["created_utc"])
        return int((dt.datetime.now(dt.timezone.utc) - start).total_seconds())
    except Exception:
        return 0


def heartbeat_loop(session_dir: Path, public_dir: Path, state: dict[str, Any], stop: threading.Event) -> None:
    while not stop.is_set():
        state["last_heartbeat_utc"] = utc_now()
        atomic_json(session_dir / "HEARTBEAT.json", {"last_heartbeat_utc": state["last_heartbeat_utc"], "state": state.get("state")})
        atomic_json(session_dir / "STATE.json", state)
        write_status(session_dir, public_dir, state)
        stop.wait(5)


def worker(args: argparse.Namespace) -> int:
    session_dir = ROOT / args.session_id
    public_dir = PUBLIC_ROOT / args.session_id
    state = load_json(session_dir / "STATE.json", {})
    config = cfg()
    router = RouterSSH(config["router"])
    stop = threading.Event()

    def handle(_signum: int, _frame: Any) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    try:
        problems = preflight(config)
        if problems:
            state.update({"state": "BLOCKED_PREFLIGHT", "problems": problems})
            atomic_json(session_dir / "STATE.json", state)
            atomic_json(ACTIVE, state)
            return 2
        baseline = collect_baseline(router, session_dir)
        session_map = identify_session_map(baseline)
        state.update(
            {
                "state": "RUNNING",
                "skill": SKILL_NAME,
                "skill_version": SKILL_VERSION,
                "session_map": session_map,
                "iperf3": iperf_capabilities(),
                "traffic_loss_resolution_s": int(state.get("epoch_duration_s") or DEFAULT_EPOCH_S),
            }
        )
        atomic_json(session_dir / "session.json", {k: state[k] for k in ("session_id", "name", "profile", "skill", "skill_version", "session_map", "created_utc")})
        atomic_json(session_dir / "STATE.json", state)
        atomic_json(ACTIVE, state)
        append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "RUNNING", "skill_version": SKILL_VERSION})
        threads = [
            threading.Thread(target=gps_loop, args=(router, session_dir, stop), daemon=True),
            threading.Thread(target=lte_loop, args=(router, session_dir, "lte1", session_map, stop), daemon=True),
            threading.Thread(target=lte_loop, args=(router, session_dir, "lte2", session_map, stop), daemon=True),
            threading.Thread(target=heartbeat_loop, args=(session_dir, public_dir, state, stop), daemon=True),
        ]
        target = config.get("ping_target", "1.1.1.1")
        for path_name, path_cfg in config["paths"].items():
            threads.append(threading.Thread(target=ping_loop, args=(session_dir, path_name, path_cfg["source_ip"], session_map[path_name]["operator"], target, stop), daemon=True))
        for th in threads:
            th.start()
        traffic_loop(session_dir, state, stop)
        stop.set()
        state["state"] = "STOPPING" if (session_dir / "STOP_REQUESTED").exists() else "ABORTING"
        for th in threads:
            th.join(timeout=8)
        state["state"] = "ANALYZING"
        state["completed_utc"] = utc_now()
        atomic_json(session_dir / "STATE.json", state)
        summary = analyze_session(session_dir, public_dir)
        state["summary"] = summary
        state["state"] = "COMPLETE" if (session_dir / "STOP_REQUESTED").exists() else "ABORTED"
        atomic_json(session_dir / "STATE.json", state)
        write_status(session_dir, public_dir, state)
        if ACTIVE.exists():
            active = load_json(ACTIVE, {})
            if active.get("session_id") == args.session_id:
                ACTIVE.unlink()
        return 0
    finally:
        stop.set()
        router.close()


def create_session(name: str, epoch_duration: int, validation: bool = False) -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True)
    PUBLIC_ROOT.mkdir(parents=True, exist_ok=True)
    if ACTIVE.exists():
        active = load_json(ACTIVE, {})
        pid = active.get("worker_pid")
        if isinstance(pid, int) and Path(f"/proc/{pid}").exists():
            raise SystemExit(f"Active drive session already running: {active.get('session_id')}")
    sid = f"drive-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug(name)}"
    session_dir = ROOT / sid
    public_dir = PUBLIC_ROOT / sid
    session_dir.mkdir(parents=True, exist_ok=False)
    public_dir.mkdir(parents=True, exist_ok=False)
    state = {
        "session_id": sid,
        "name": name,
        "state": "PRESTART",
        "profile": "AUTO_DUAL_6M",
        "created_utc": utc_now(),
        "runtime_dir": str(session_dir),
        "public_dir": str(public_dir),
        "epoch_duration_s": epoch_duration,
        "current_epoch": 0,
        "validation_only": validation,
    }
    atomic_json(session_dir / "STATE.json", state)
    append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "START_REQUESTED", "name": name})
    return state


def start(args: argparse.Namespace) -> int:
    state = create_session(args.name, args.epoch_duration)
    log_base = ROOT / f"{state['session_id']}.worker"
    cmd = [sys.executable, str(Path(__file__).resolve()), "run-worker", "--session-id", state["session_id"]]
    out = (log_base.with_suffix(".stdout.log")).open("w", encoding="utf-8")
    err = (log_base.with_suffix(".stderr.log")).open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=out, stderr=err, start_new_session=True)
    state["worker_pid"] = proc.pid
    atomic_json(ROOT / state["session_id"] / "STATE.json", state)
    atomic_json(ACTIVE, state)
    print(f"LTE drive test STARTING.\nSession: {state['session_id']}\nRecording: starting")
    return 0


def stop_cmd(_args: argparse.Namespace) -> int:
    active = load_json(ACTIVE, {})
    sid = active.get("session_id")
    if not sid:
        print("No active drive session.")
        return 1
    session_dir = ROOT / sid
    (session_dir / "STOP_REQUESTED").write_text(utc_now() + "\n", encoding="utf-8")
    append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "STOP_REQUESTED"})
    print(f"STOP requested for {sid}")
    return 0


def status_cmd(_args: argparse.Namespace) -> int:
    active = load_json(ACTIVE, {})
    sid = active.get("session_id")
    if not sid:
        print("No active drive session.")
        return 1
    status = PUBLIC_ROOT / sid / "STATUS.md"
    print(status.read_text(encoding="utf-8") if status.exists() else json.dumps(active, indent=2))
    return 0


def mark_cmd(args: argparse.Namespace) -> int:
    active = load_json(ACTIVE, {})
    sid = active.get("session_id")
    if not sid:
        print("No active drive session.")
        return 1
    session_dir = ROOT / sid
    row = {
        "utc": utc_now(),
        "type": "HUMAN_MARK",
        "label": args.label,
        "gps": latest_sample(session_dir / "gps.jsonl"),
        "lte1": latest_sample(session_dir / "lte1.jsonl"),
        "lte2": latest_sample(session_dir / "lte2.jsonl"),
        "ping_lte1": latest_sample(session_dir / "ping_lte1.jsonl"),
        "ping_lte2": latest_sample(session_dir / "ping_lte2.jsonl"),
    }
    append_jsonl(session_dir / "events.jsonl", row)
    print(f"Marked: {args.label}")
    return 0


def analyze_cmd(args: argparse.Namespace) -> int:
    sid = args.session_id
    summary = analyze_session(ROOT / sid, PUBLIC_ROOT / sid)
    print(json.dumps(summary, indent=2))
    return 0


def validate_cmd(args: argparse.Namespace) -> int:
    state = create_session("skill-v2-validation-only", args.epoch_duration, validation=True)
    session_dir = ROOT / state["session_id"]
    log_base = ROOT / f"{state['session_id']}.worker"
    cmd = [sys.executable, str(Path(__file__).resolve()), "run-worker", "--session-id", state["session_id"]]
    out = (log_base.with_suffix(".stdout.log")).open("w", encoding="utf-8")
    err = (log_base.with_suffix(".stderr.log")).open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=out, stderr=err, start_new_session=True)
    state["worker_pid"] = proc.pid
    atomic_json(session_dir / "STATE.json", state)
    atomic_json(ACTIVE, state)
    deadline = time.time() + args.duration
    while time.time() < deadline:
        time.sleep(1)
    traffic_marker = session_dir / "traffic_lte1.jsonl"
    previous_count = line_count(traffic_marker)
    wait_epoch_deadline = time.time() + max(30, args.epoch_duration * 3)
    while time.time() < wait_epoch_deadline:
        current_count = line_count(traffic_marker)
        if current_count > previous_count:
            break
        time.sleep(0.5)
    time.sleep(min(3.0, max(1.0, args.epoch_duration / 2)))
    (session_dir / "STOP_REQUESTED").write_text(utc_now() + "\n", encoding="utf-8")
    append_jsonl(session_dir / "events.jsonl", {"utc": utc_now(), "type": "STOP_REQUESTED", "validation": "MID_EPOCH_STOP"})
    try:
        rc = proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait(timeout=10)
    print(state["session_id"])
    return 0 if rc == 0 else 1


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--name", required=True)
    s.add_argument("--epoch-duration", type=int, default=DEFAULT_EPOCH_S)
    s.set_defaults(func=start)
    w = sub.add_parser("run-worker")
    w.add_argument("--session-id", required=True)
    w.set_defaults(func=worker)
    sub.add_parser("status").set_defaults(func=status_cmd)
    sub.add_parser("stop").set_defaults(func=stop_cmd)
    m = sub.add_parser("mark")
    m.add_argument("label")
    m.set_defaults(func=mark_cmd)
    a = sub.add_parser("analyze")
    a.add_argument("--session-id", required=True)
    a.set_defaults(func=analyze_cmd)
    v = sub.add_parser("validate")
    v.add_argument("--duration", type=int, default=190)
    v.add_argument("--epoch-duration", type=int, default=10)
    v.set_defaults(func=validate_cmd)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
