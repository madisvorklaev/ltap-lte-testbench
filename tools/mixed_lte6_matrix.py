#!/usr/bin/env python3
"""Durable mixed LTE6 controlled band campaign runner for the LtAP public iPerf lab."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
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
COLLECTOR_PATH = REPO / "references/public-iperf-kit/ltap_public_test.py"
CONFIG = REPO / "references/public-iperf-kit/config.json"
CAMPAIGN_LTE1 = REPO / "references/public-iperf-kit/campaign-dual-lte1.json"
CAMPAIGN_LTE2 = REPO / "references/public-iperf-kit/campaign-dual-lte2.json"
CAMPAIGN = REPO / "references/public-iperf-kit/campaign.json"
CAMPAIGN_ID = "mixed-lte6-matrix-7.24rc3"
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
PUBLIC = REPO / "results-public" / CAMPAIGN_ID
STOP_FILE = REPO / "runtime/STOP_MIXED_LTE6_MATRIX"
BRANCH = "mixed-lte6-matrix-7.24rc3"
TARGET_VERSION = "7.24rc3"


SENSITIVE_KEYS = {
    "imei",
    "imsi",
    "iccid",
    "uicc",
    "subscriber-number",
    "serial-number",
    "software-id",
}

TERMINAL_ITEM_STATES = {"COMPLETE", "SKIPPED_BAND_UNAVAILABLE", "FAILED_AFTER_RETRIES"}
COMMON_FDD_NO_B38 = "1,3,7,8,20"


def load_collector() -> Any:
    spec = importlib.util.spec_from_file_location("ltap_public_test", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import collector from {COLLECTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_collector()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_now_tag() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=timeout)


def raise_system_exit(code: int) -> None:
    raise SystemExit(code)


def sanitize_text(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        key = line.split(":", 1)[0].strip().lower() if ":" in line else ""
        if key in SENSITIVE_KEYS:
            continue
        if re.search(r"\b(imsi|imei|iccid|uicc|subscriber-number|serial-number|software-id)\b", line, re.I):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key.lower() in SENSITIVE_KEYS:
                continue
            if key.endswith("_raw") and isinstance(value, str):
                out[key] = sanitize_text(value)
            else:
                out[key] = sanitize_obj(value)
        return out
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, str):
        return sanitize_text(obj)
    return obj


def items() -> list[dict[str, Any]]:
    primary = [
        ("M0", "", ""),
        ("M1", COMMON_FDD_NO_B38, COMMON_FDD_NO_B38),
        ("M2", "3", "3"),
        ("M3", "3", "7"),
        ("M4", "7", "3"),
        ("M5", "38", "3"),
        ("M6", "3", "38"),
    ]
    coverage = [
        ("C1", "20", "3"),
        ("C2", "3", "20"),
        ("C3", "1", "3"),
        ("C4", "3", "1"),
        ("C5", "8", "3"),
        ("C6", "3", "8"),
    ]
    out: list[dict[str, Any]] = []
    for round_name, seq in (("R1", primary), ("R2", list(reversed(primary)))):
        for code, lte1, lte2 in seq:
            out.append({
                "id": f"{round_name}-{code}",
                "phase": "PRIMARY_DUAL_MATRIX",
                "round": round_name,
                "matrix": code,
                "mode": "dual",
                "lte1_band": lte1,
                "lte2_band": lte2,
                "lte1_bitrate": "6M",
                "lte2_bitrate": "6M",
                "duration": 300,
                "packet_length": 1200,
                "required": True,
            })
    for code, lte1, lte2 in coverage:
        out.append({
            "id": code,
            "phase": "COVERAGE_DUAL_MATRIX",
            "round": "coverage",
            "matrix": code,
            "mode": "dual",
            "lte1_band": lte1,
            "lte2_band": lte2,
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
        })
    singles = [
        ("S1", "lte1", "3"),
        ("S2", "lte2", "3"),
        ("S3", "lte1", "7"),
        ("S4", "lte2", "7"),
        ("S5", "lte1", "38"),
        ("S6", "lte2", "38"),
    ]
    for code, path, band in singles:
        out.append({
            "id": code,
            "phase": "SINGLE_PATH_DIAGNOSTICS",
            "round": "single",
            "matrix": code,
            "mode": "single",
            "path": path,
            "lte1_band": band if path == "lte1" else None,
            "lte2_band": band if path == "lte2" else None,
            "bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
        })
    for path in ("lte1", "lte2"):
        for rate in ("4M", "6M", "8M", "10M", "12M"):
            out.append({
                "id": f"H-{path.upper()}-{rate}",
                "phase": "B3_HEADROOM_STAIRCASE",
                "round": "headroom",
                "matrix": "B3",
                "mode": "single",
                "path": path,
                "lte1_band": "3",
                "lte2_band": "3",
                "bitrate": rate,
                "duration": 60,
                "packet_length": 1200,
                "required": True,
            })
    for candidate, lte1, lte2 in (("L1", "3", "7"), ("L2", "3", "3")):
        for repeat in (1, 2, 3):
            out.append({
                "id": f"{candidate}-R{repeat}",
                "phase": "LONG_STABILITY",
                "round": "long-stability",
                "matrix": candidate,
                "mode": "dual",
                "lte1_band": lte1,
                "lte2_band": lte2,
                "lte1_bitrate": "6M",
                "lte2_bitrate": "6M",
                "duration": 600,
                "packet_length": 1200,
                "required": True,
                "note": "seeded from prior best candidates; final ranking is updated in the report",
            })
    return out


def item_map() -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in items()}


class Runner:
    def __init__(self) -> None:
        self.cfg = load_json(CONFIG)
        self.campaign = load_json(CAMPAIGN)
        self.router = collector.RouterSSH(self.cfg["router"])
        self.progress_path = RUNTIME / "PROGRESS.json"
        self.heartbeat_path = RUNTIME / "HEARTBEAT.json"
        self.progress = self.load_or_init_progress()
        self.current_state = "STARTING"
        self.last_error = ""
        self.last_telemetry = None
        self.router_reachable = False
        self.server_reachable = False
        self.worker_progress_counter = int(self.progress.get("worker_progress_counter", 0))
        self.worker_last_progress_at = self.progress.get("worker_last_progress_at") or now()
        self.item_started_mono: float | None = None
        self.stop_heartbeat = threading.Event()
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)

    def load_or_init_progress(self) -> dict[str, Any]:
        loaded = load_json(self.progress_path)
        if loaded:
            return loaded
        now_s = now()
        item_states = {x["id"]: {"state": "PENDING", "attempts": 0, "history": []} for x in items()}
        progress = {
            "schema_version": 2,
            "campaign_id": CAMPAIGN_ID,
            "state": "STARTING",
            "started_at": now_s,
            "updated_at": now_s,
            "routeros": None,
            "modem_lte1": {"expected": "FG621-EA", "detected": None, "firmware": None},
            "modem_lte2": {"expected": "R11e-LTE6", "detected": None, "firmware": None},
            "original_band_lte1": None,
            "original_band_lte2": None,
            "server_epoch": 1,
            "server_hostname": self.campaign.get("server_hostname"),
            "server_ipv4": self.campaign.get("server_ipv4"),
            "completed_count": 0,
            "mandatory_total": len(items()),
            "current_item": None,
            "retry_queue": [],
            "push_pending": False,
            "bands_restored": False,
            "items": item_states,
            "last_pushed_commit": None,
            "worker_progress_counter": 0,
            "worker_last_progress_at": now_s,
        }
        self.save_progress(progress)
        return progress

    def save_progress(self, progress: dict[str, Any] | None = None) -> None:
        if progress is not None:
            self.progress = progress
        self.progress["updated_at"] = now()
        self.progress["worker_progress_counter"] = self.worker_progress_counter
        self.progress["worker_last_progress_at"] = self.worker_last_progress_at
        self.progress["completed_count"] = sum(
            1 for item in self.progress["items"].values()
            if item.get("state") in TERMINAL_ITEM_STATES
        )
        atomic_write_json(self.progress_path, self.progress)
        public_progress = sanitize_obj(self.progress)
        atomic_write_json(PUBLIC / "PROGRESS.json", public_progress)

    def transition(self, item_id: str, state: str, **fields: Any) -> None:
        item = self.progress["items"][item_id]
        item.update(fields)
        item["state"] = state
        item.setdefault("history", []).append({"at": now(), "state": state, **fields})
        self.progress["current_item"] = item_id
        self.progress["state"] = item_map()[item_id].get("phase", "RUNNING")
        self.current_state = state
        if state == "RUNNING":
            self.item_started_mono = time.monotonic()
        self.bump_worker_progress()
        self.save_progress()

    def bump_worker_progress(self) -> None:
        self.worker_progress_counter += 1
        self.worker_last_progress_at = now()

    def heartbeat_loop(self) -> None:
        while not self.stop_heartbeat.is_set():
            bands = self.read_band_values(suppress_errors=True)
            heartbeat = {
                "timestamp": now(),
                "pid": os.getpid(),
                "campaign_state": self.progress.get("state"),
                "current_item": self.progress.get("current_item"),
                "item_state": self.current_state,
                "item_elapsed_s": int(time.monotonic() - self.item_started_mono) if self.item_started_mono else 0,
                "worker_progress_counter": self.worker_progress_counter,
                "worker_last_progress_at": self.worker_last_progress_at,
                "elapsed_seconds": int(time.time() - dt.datetime.fromisoformat(self.progress["started_at"]).timestamp()),
                "last_successful_telemetry_timestamp": self.last_telemetry,
                "router_reachable": self.router_reachable,
                "server_reachable": self.server_reachable,
                "lte1_status": None,
                "lte2_status": None,
                "lte1_band_config": bands.get("lte1"),
                "lte2_band_config": bands.get("lte2"),
                "completed": self.progress.get("completed_count", 0),
                "mandatory_total": self.progress.get("mandatory_total", len(items())),
                "retry_queue_length": sum(1 for x in self.progress["items"].values() if x.get("state") == "RETRY_PENDING"),
                "push_pending": self.progress.get("push_pending", False),
                "last_error": self.last_error,
                "last_local_commit": run(["git", "rev-parse", "--short", "HEAD"], timeout=10).stdout.strip(),
                "last_pushed_commit": self.progress.get("last_pushed_commit"),
                "bands_currently_configured": bands,
            }
            atomic_write_json(self.heartbeat_path, heartbeat)
            atomic_write_json(PUBLIC / "HEARTBEAT.json", sanitize_obj(heartbeat))
            self.stop_heartbeat.wait(30)

    def start_heartbeat(self) -> None:
        self.heartbeat_thread.start()

    def close(self) -> None:
        self.stop_heartbeat.set()
        if self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=3)
        try:
            self.router.close()
        except Exception:
            pass

    def router_call(self, command: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
        cp = self.router.call(command, timeout=timeout)
        self.router_reachable = cp.returncode == 0
        if cp.returncode != 0:
            self.last_error = cp.stderr.strip() or f"Router command failed: {command}"
        return cp

    def read_band_values(self, suppress_errors: bool = False) -> dict[str, str | None]:
        try:
            cp = self.router.call("/interface/lte/print detail without-paging", timeout=8)
            self.router_reachable = cp.returncode == 0
            if cp.returncode != 0:
                if not suppress_errors:
                    raise RuntimeError(cp.stderr.strip())
                return {"lte1": None, "lte2": None}
            return {
                "lte1": self.parse_band(cp.stdout, "lte1"),
                "lte2": self.parse_band(cp.stdout, "lte2"),
            }
        except Exception as exc:
            if not suppress_errors:
                raise
            self.last_error = repr(exc)
            self.router_reachable = False
            return {"lte1": None, "lte2": None}

    @staticmethod
    def parse_band(raw: str, iface: str) -> str:
        compact = " ".join(raw.splitlines())
        block = re.search(rf'name="{re.escape(iface)}"(?P<body>.*?)(?:\s+\d+\s+[R ]?\s*default-name=|$)', compact)
        body = block.group("body") if block else compact
        m = re.search(r'band=(?:"([^"]*)"|([^"\s]+))', body)
        if not m:
            return ""
        return (m.group(1) if m.group(1) is not None else m.group(2)) or ""

    def set_band(self, iface: str, band: str) -> None:
        escaped = band.replace('"', '\\"')
        cp = self.router_call(f'/interface/lte/set [find where name="{iface}"] band="{escaped}"', timeout=10)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr.strip() or f"failed setting {iface} band")

    def monitor(self, iface: str) -> dict[str, str]:
        cp = self.router_call(f"/interface/lte/monitor {iface} once", timeout=8)
        if cp.returncode != 0:
            return {}
        self.last_telemetry = now()
        return collector.parse_lte_monitor(cp.stdout)

    def verify_topology(self) -> bool:
        detail = self.router_call("/interface/lte/print detail without-paging", timeout=15).stdout
        lte1 = self.monitor("lte1")
        lte2 = self.monitor("lte2")
        self.progress["modem_lte1"] = {
            "expected": "FG621-EA",
            "detected": lte1.get("model") or self.extract_interface_model(detail, "lte1"),
            "firmware": lte1.get("revision"),
        }
        self.progress["modem_lte2"] = {
            "expected": "R11e-LTE6",
            "detected": lte2.get("model") or self.extract_interface_model(detail, "lte2"),
            "firmware": lte2.get("revision"),
        }
        lte1_ok = re.search(r"(FG621|R11eL-FG621)", str(self.progress["modem_lte1"]["detected"]), re.I) is not None
        lte2_ok = re.search(r"R11e-LTE6|LTE6", str(self.progress["modem_lte2"]["detected"]), re.I) is not None
        if not lte1_ok or not lte2_ok:
            self.progress["state"] = "BLOCKED_TOPOLOGY_MISMATCH"
            self.last_error = f"Topology mismatch: lte1={self.progress['modem_lte1']} lte2={self.progress['modem_lte2']}"
            self.save_progress()
            return False
        self.save_progress()
        return True

    @staticmethod
    def extract_interface_model(raw: str, iface: str) -> str | None:
        compact = " ".join(raw.splitlines())
        block = re.search(rf'name="{re.escape(iface)}"(?P<body>.*?)(?:\s+\d+\s+[R ]?\s*default-name=|$)', compact)
        body = block.group("body") if block else compact
        m = re.search(r'model=(?:"([^"]*)"|([^"\s]+))', body)
        if not m:
            return None
        return m.group(1) if m.group(1) is not None else m.group(2)

    def wait_registered_and_verified(self, item: dict[str, Any]) -> bool:
        deadline = time.time() + 120
        needed = self.desired_bands(item)
        ok_once = False
        while time.time() < deadline:
            all_ok = True
            for iface in ("lte1", "lte2"):
                mon = self.monitor(iface)
                if mon.get("status") != "registered":
                    all_ok = False
                    continue
                if not self.primary_band_allowed(mon.get("primary-band", ""), needed[iface]):
                    all_ok = False
            if all_ok:
                ok_once = True
                break
            time.sleep(5)
        if not ok_once:
            return False
        stable_until = time.time() + 30
        while time.time() < stable_until:
            for iface in ("lte1", "lte2"):
                mon = self.monitor(iface)
                if mon.get("status") != "registered":
                    return False
            time.sleep(5)
        return True

    @staticmethod
    def primary_band_allowed(primary: str, setting: str) -> bool:
        if setting is None:
            return True
        if setting == "":
            return True
        m = re.match(r"B([0-9]+)@", primary or "")
        if not m:
            return False
        return m.group(1) in {x.strip() for x in setting.split(",") if x.strip()}

    def desired_bands(self, item: dict[str, Any]) -> dict[str, str | None]:
        return {
            "lte1": item.get("lte1_band"),
            "lte2": item.get("lte2_band"),
        }

    def verify_versions(self) -> bool:
        resource = self.router_call("/system/resource/print", timeout=8).stdout
        routerboard = self.router_call("/system/routerboard/print", timeout=8).stdout
        routeros_ok = f"version: {TARGET_VERSION}" in resource
        firmware_ok = f"current-firmware: {TARGET_VERSION}" in routerboard
        self.progress["routeros"] = TARGET_VERSION if routeros_ok else "MISMATCH"
        self.progress["routerboard_firmware"] = TARGET_VERSION if firmware_ok else "MISMATCH"
        if not routeros_ok or not firmware_ok:
            self.progress["state"] = "BLOCKED_VERSION_MISMATCH"
            self.last_error = f"RouterOS/FW mismatch. resource={resource!r} routerboard={routerboard!r}"
            self.save_progress()
            return False
        return True

    def save_original_bands(self) -> None:
        if self.progress.get("original_band_lte1") is not None:
            return
        bands = self.read_band_values()
        self.progress["original_band_lte1"] = bands["lte1"] or ""
        self.progress["original_band_lte2"] = bands["lte2"] or ""
        detail = self.router_call("/interface/lte/print detail without-paging", timeout=8).stdout
        (RUNTIME / "original_lte_detail.txt").parent.mkdir(parents=True, exist_ok=True)
        (RUNTIME / "original_lte_detail.txt").write_text(detail, encoding="utf-8")
        self.save_progress()

    def verify_lab_routes(self) -> bool:
        checks = [
            self.router_call('/ip/firewall/mangle/print stats where comment="ELMO TEST: source via lte1"', timeout=15),
            self.router_call('/ip/firewall/mangle/print stats where comment="ELMO TEST: source via lte2"', timeout=15),
            run(["ip", "route", "get", "1.1.1.1", "from", "192.168.101.201"], timeout=10),
            run(["ip", "route", "get", "1.1.1.1", "from", "192.168.101.202"], timeout=10),
        ]
        ok = all(cp.returncode == 0 for cp in checks)
        if not ok:
            self.progress["state"] = "WAIT_NETWORK"
            self.last_error = "Lab source routing preflight failed"
            self.save_progress()
        return ok

    def server_probe(self) -> bool:
        cp = run([
            "iperf3", "-c", self.campaign["server_ipv4"], "-p", "5201",
            "-4", "-t", "1", "-J",
        ], timeout=8)
        self.server_reachable = cp.returncode == 0 or "server is busy" in (cp.stderr + cp.stdout).lower()
        return self.server_reachable

    def wait_until(self, state: str, predicate: Any, interval: int) -> None:
        self.progress["state"] = state
        self.save_progress()
        while not STOP_FILE.exists():
            try:
                if predicate():
                    return
            except Exception as exc:
                self.last_error = repr(exc)
                self.save_progress()
            time.sleep(interval)

    def run_smoke_tests(self) -> None:
        if self.progress.get("smoke_tests_completed"):
            return
        smoke_items = [
            {"id": "SMOKE-LTE1", "mode": "single", "path": "lte1", "bitrate": "1M", "duration": 10, "packet_length": 1200},
            {"id": "SMOKE-LTE2", "mode": "single", "path": "lte2", "bitrate": "1M", "duration": 10, "packet_length": 1200},
            {"id": "SMOKE-DUAL", "mode": "dual", "lte1_bitrate": "1M", "lte2_bitrate": "1M", "duration": 20, "packet_length": 1200},
        ]
        results: dict[str, Any] = {}
        for smoke in smoke_items:
            self.current_state = f"SMOKE_{smoke['id']}"
            self.bump_worker_progress()
            if smoke["mode"] == "single":
                ok, data = self.run_single(smoke, 1)
            else:
                ok, data = self.run_dual(smoke, 1)
            results[smoke["id"]] = {"ok": ok, "status": data.get("dual_status"), "raw_root": data.get("raw_root")}
            if not ok:
                self.progress["state"] = "WAIT_SERVER"
                self.last_error = f"Smoke test failed: {smoke['id']} {data.get('dual_status')}"
                self.save_progress()
                raise RuntimeError(self.last_error)
        self.progress["smoke_tests_completed"] = True
        self.progress["smoke_tests"] = results
        self.save_progress()

    def run_dual(self, item: dict[str, Any], attempt: int) -> tuple[bool, dict[str, Any]]:
        item_id = item["id"]
        raw_root = RUNTIME / "raw" / item_id / f"attempt-{attempt}"
        raw_root.mkdir(parents=True, exist_ok=True)
        tag = f"{CAMPAIGN_ID}_{item_id}_a{attempt}_{local_now_tag()}"
        py = str(REPO / ".venv/bin/python")
        base = [py, str(COLLECTOR_PATH), "--config", str(CONFIG), "run"]
        duration = str(item.get("duration", 300))
        packet_length = str(item.get("packet_length", 1200))
        commands = [
            base + ["--campaign", str(CAMPAIGN_LTE1), "--path", "lte1", "--protocol", "udp", "--bitrate", item.get("lte1_bitrate", "6M"), "--packet-length", packet_length, "--duration", duration, "--warmup", "10", "--cooldown", "10", "--allow-concurrent-other-lte", "--tag", f"{tag}_lte1", "--output", str(raw_root)],
            base + ["--campaign", str(CAMPAIGN_LTE2), "--path", "lte2", "--protocol", "udp", "--bitrate", item.get("lte2_bitrate", "6M"), "--packet-length", packet_length, "--duration", duration, "--warmup", "10", "--cooldown", "10", "--allow-concurrent-other-lte", "--tag", f"{tag}_lte2", "--output", str(raw_root)],
        ]
        procs = [
            subprocess.Popen(cmd, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for cmd in commands
        ]
        results = []
        for proc in procs:
            try:
                stdout, stderr = proc.communicate(timeout=int(item.get("duration", 300)) + 90)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=10)
                stderr = (stderr or "") + "\nTIMEOUT: collector exceeded bounded runtime"
            results.append({"rc": proc.returncode, "stdout": stdout, "stderr": stderr})
            self.bump_worker_progress()
        (raw_root / "processes.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        summary_paths = sorted(raw_root.glob("*/summary.json"))
        summaries = [load_json(path) for path in summary_paths]
        by_path = {s.get("test", {}).get("path"): s for s in summaries if isinstance(s, dict)}
        ok = (
            len(by_path) == 2
            and all(r["rc"] == 0 for r in results)
            and all((by_path[p].get("path_verification") or "").startswith("PASS") for p in ("lte1", "lte2"))
        )
        combined = {
            "item": item,
            "attempt": attempt,
            "raw_root": str(raw_root),
            "processes": [{"rc": x["rc"], "stderr_tail": x["stderr"][-1000:]} for x in results],
            "lte1": by_path.get("lte1"),
            "lte2": by_path.get("lte2"),
            "dual_status": "PASS_DUAL" if ok else "FAIL_IPERF_OR_PATH",
        }
        return ok, combined

    def run_single(self, item: dict[str, Any], attempt: int) -> tuple[bool, dict[str, Any]]:
        item_id = item["id"]
        path = item["path"]
        raw_root = RUNTIME / "raw" / item_id / f"attempt-{attempt}"
        raw_root.mkdir(parents=True, exist_ok=True)
        tag = f"{CAMPAIGN_ID}_{item_id}_a{attempt}_{local_now_tag()}_{path}"
        py = str(REPO / ".venv/bin/python")
        campaign = CAMPAIGN_LTE1 if path == "lte1" else CAMPAIGN_LTE2
        command = [
            py, str(COLLECTOR_PATH), "--config", str(CONFIG), "run",
            "--campaign", str(campaign),
            "--path", path,
            "--protocol", "udp",
            "--bitrate", item.get("bitrate", "6M"),
            "--packet-length", str(item.get("packet_length", 1200)),
            "--duration", str(item.get("duration", 300)),
            "--warmup", "10",
            "--cooldown", "10",
            "--tag", tag,
            "--output", str(raw_root),
        ]
        try:
            cp = subprocess.run(
                command,
                cwd=REPO,
                text=True,
                capture_output=True,
                timeout=int(item.get("duration", 300)) + 90,
            )
            result = {"rc": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}
        except subprocess.TimeoutExpired as exc:
            result = {"rc": 124, "stdout": exc.stdout or "", "stderr": (exc.stderr or "") + "\nTIMEOUT: collector exceeded bounded runtime"}
        (raw_root / "processes.json").write_text(json.dumps([result], indent=2), encoding="utf-8")
        summary_paths = sorted(raw_root.glob("*/summary.json"))
        summaries = [load_json(path_) for path_ in summary_paths]
        summary = next((s for s in summaries if isinstance(s, dict) and s.get("test", {}).get("path") == path), None)
        ok = result["rc"] == 0 and summary is not None and (summary.get("path_verification") or "").startswith("PASS")
        combined = {
            "item": item,
            "attempt": attempt,
            "raw_root": str(raw_root),
            "processes": [{"rc": result["rc"], "stderr_tail": result["stderr"][-1000:]}],
            path: summary,
            "dual_status": "PASS_SINGLE" if ok else "FAIL_SINGLE_PATH",
        }
        self.bump_worker_progress()
        return ok, combined

    def publish_run(self, item_id: str, data: dict[str, Any]) -> None:
        run_dir = PUBLIC / "runs" / item_id
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "summary.json", sanitize_obj(data))
        atomic_write_json(run_dir / "manifest.json", {
            "campaign_id": CAMPAIGN_ID,
            "item_id": item_id,
            "published_at": now(),
            "raw_artifacts_local": data.get("raw_root"),
            "raw_sensitive_not_committed": True,
        })
        for path_name in ("lte1", "lte2"):
            summary = data.get(path_name) or {}
            raw_root = Path(data.get("raw_root") or "")
            test_dir = summary.get("test", {}).get("tag")
            if raw_root.exists() and test_dir:
                matches = list(raw_root.glob(f"*{test_dir}*"))
                if matches:
                    self.publish_sanitized_artifacts(matches[0], run_dir, path_name)
        self.update_matrix_summary()

    def publish_sanitized_artifacts(self, raw_dir: Path, run_dir: Path, path_name: str) -> None:
        for src_name, dst_name in (
            ("iperf.json", f"iperf_{path_name}.json"),
            ("ping.txt", f"ping_{path_name}.txt"),
            ("events.jsonl", f"events_{path_name}.jsonl"),
        ):
            src = raw_dir / src_name
            if src.exists():
                shutil.copyfile(src, run_dir / dst_name)
        tele = raw_dir / "telemetry.jsonl"
        if tele.exists():
            out = run_dir / f"telemetry_sanitized_{path_name}.jsonl"
            with tele.open("r", encoding="utf-8") as src, out.open("w", encoding="utf-8") as dst:
                for line in src:
                    try:
                        dst.write(json.dumps(sanitize_obj(json.loads(line)), ensure_ascii=False) + "\n")
                    except json.JSONDecodeError:
                        continue

    def update_matrix_summary(self) -> None:
        rows: list[dict[str, Any]] = []
        summary_obj: dict[str, Any] = {"campaign_id": CAMPAIGN_ID, "updated_at": now(), "items": {}}
        for item_id, state in self.progress["items"].items():
            run_summary = load_json(PUBLIC / "runs" / item_id / "summary.json", {})
            row = {
                "item_id": item_id,
                "state": state.get("state"),
                "attempts": state.get("attempts", 0),
                "lte1_band": item_map()[item_id]["lte1_band"],
                "lte2_band": item_map()[item_id]["lte2_band"],
                "dual_status": run_summary.get("dual_status"),
            }
            for path_name in ("lte1", "lte2"):
                ps = (run_summary.get(path_name) or {})
                iperf = ps.get("iperf") or {}
                ping = ps.get("ping") or {}
                row[f"{path_name}_mbps"] = iperf.get("mbps")
                row[f"{path_name}_loss_percent"] = iperf.get("lost_percent")
                row[f"{path_name}_ping_p95_ms"] = ping.get("p95_ms")
            rows.append(row)
            summary_obj["items"][item_id] = row
        csv_path = PUBLIC / "matrix_summary.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0].keys()) if rows else []
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        atomic_write_json(PUBLIC / "matrix_summary.json", summary_obj)
        self.write_report(summary_obj)

    def write_report(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# LtAP Band Matrix {CAMPAIGN_ID}",
            "",
            f"Updated: {summary_obj['updated_at']}",
            "",
            "This report is generated incrementally. Final production recommendations are intentionally withheld until all required items are terminal.",
            "",
            "| Item | State | LTE1 band | LTE2 band | Status | LTE1 Mbps | LTE1 loss % | LTE1 p95 ms | LTE2 Mbps | LTE2 loss % | LTE2 p95 ms |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item_id, row in summary_obj["items"].items():
            lines.append(
                f"| {item_id} | {row.get('state')} | {row.get('lte1_band')} | {row.get('lte2_band')} | {row.get('dual_status') or ''} | "
                f"{row.get('lte1_mbps') or ''} | {row.get('lte1_loss_percent') or ''} | {row.get('lte1_ping_p95_ms') or ''} | "
                f"{row.get('lte2_mbps') or ''} | {row.get('lte2_loss_percent') or ''} | {row.get('lte2_ping_p95_ms') or ''} |"
            )
        (PUBLIC / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def git_checkpoint(self, message: str) -> None:
        paths = ["tools/mixed_lte6_matrix.py", "tools/ltap_mixed_lte6_watchdog.py", "results-public/mixed-lte6-matrix-7.24rc3"]
        run(["git", "add", *paths], timeout=30)
        staged = run(["git", "diff", "--cached", "--name-only"], timeout=30).stdout.splitlines()
        if not staged:
            return
        scan = run(["bash", "-lc", "git diff --cached --name-only -z | xargs -0 rg -n -i 'password|pin|imsi|imei|iccid|uicc|serial-number|software-id|private key' || true"], timeout=30)
        bad_lines = [line for line in scan.stdout.splitlines() if "README.md:" not in line]
        if bad_lines:
            self.progress["push_pending"] = True
            self.last_error = "Secret scan blocked commit: " + "; ".join(bad_lines[:3])
            self.save_progress()
            run(["git", "reset"], timeout=30)
            return
        commit = run(["git", "commit", "-m", message], timeout=60)
        if commit.returncode not in (0, 1):
            self.progress["push_pending"] = True
            self.last_error = commit.stderr.strip()
            self.save_progress()
            return
        push = run(["git", "push", "-u", "origin", BRANCH], timeout=120)
        if push.returncode != 0:
            self.progress["push_pending"] = True
            self.last_error = push.stderr.strip()
        else:
            head = run(["git", "rev-parse", "HEAD"], timeout=10).stdout.strip()
            self.progress["last_pushed_commit"] = head
            self.progress["push_pending"] = False
        self.save_progress()

    def restore_bands(self) -> bool:
        self.progress["state"] = "RESTORING_BANDS"
        self.save_progress()
        try:
            self.set_band("lte1", self.progress.get("original_band_lte1") or "")
            self.set_band("lte2", self.progress.get("original_band_lte2") or "")
            time.sleep(10)
            bands = self.read_band_values()
            ok = (
                (bands["lte1"] or "") == (self.progress.get("original_band_lte1") or "")
                and (bands["lte2"] or "") == (self.progress.get("original_band_lte2") or "")
            )
            if ok:
                self.progress["bands_restored"] = True
                self.progress["state"] = "COMPLETE"
                self.save_progress()
            return ok
        except Exception as exc:
            self.last_error = repr(exc)
            self.progress["state"] = "RESTORE_RETRY"
            self.save_progress()
            return False

    def restore_until_verified(self) -> None:
        while not self.restore_bands():
            self.current_state = "RESTORE_RETRY"
            self.bump_worker_progress()
            time.sleep(60)

    def run(self) -> None:
        self.start_heartbeat()
        try:
            if not self.verify_versions():
                self.wait_until("BLOCKED_VERSION_MISMATCH", self.verify_versions, 300)
            if not self.verify_topology():
                self.wait_until("BLOCKED_TOPOLOGY_MISMATCH", self.verify_topology, 300)
            if not self.verify_lab_routes():
                self.wait_until("WAIT_NETWORK", self.verify_lab_routes, 120)
            self.save_original_bands()
            if not self.server_probe():
                self.wait_until("WAIT_SERVER", self.server_probe, 600)
            while not self.progress.get("smoke_tests_completed") and not STOP_FILE.exists():
                try:
                    self.run_smoke_tests()
                except Exception:
                    time.sleep(600)
            self.progress["state"] = "RUNNING"
            self.save_progress()
            self.git_checkpoint("mixed-lte6: initialize progress")
            for item in items():
                item_state = self.progress["items"][item["id"]]
                if item_state.get("state") in TERMINAL_ITEM_STATES:
                    continue
                if STOP_FILE.exists():
                    break
                self.run_item(item)
            if STOP_FILE.exists() or all(
                x.get("state") in TERMINAL_ITEM_STATES
                for x in self.progress["items"].values()
            ):
                self.restore_until_verified()
                self.update_matrix_summary()
                self.git_checkpoint("mixed-lte6: update completion state")
        finally:
            self.close()

    def run_item(self, item: dict[str, Any]) -> None:
        item_id = item["id"]
        attempts = int(self.progress["items"][item_id].get("attempts", 0))
        try:
            self.transition(item_id, "APPLYING_BANDS", attempts=attempts)
            verified = False
            desired = self.desired_bands(item)
            for cycle in range(2):
                if STOP_FILE.exists():
                    return
                for iface, band in desired.items():
                    if band is not None:
                        self.set_band(iface, band)
                time.sleep(5)
                bands = self.read_band_values()
                readback_ok = all((bands[iface] or "") == band for iface, band in desired.items() if band is not None)
                if not readback_ok:
                    self.progress["items"][item_id]["last_error"] = f"band readback mismatch: {bands}"
                    self.save_progress()
                    continue
                self.transition(item_id, "WAITING_REGISTRATION", bands=bands)
                if self.wait_registered_and_verified(item):
                    verified = True
                    break
            if not verified:
                self.transition(item_id, "SKIPPED_BAND_UNAVAILABLE", bands=self.read_band_values(suppress_errors=True), last_error="band did not register/verify")
                self.update_matrix_summary()
                self.git_checkpoint(f"mixed-lte6: {item_id} skipped unavailable")
                return
            self.transition(item_id, "READY")
            for _ in range(3 - attempts):
                if STOP_FILE.exists():
                    return
                attempts += 1
                self.progress["items"][item_id]["attempts"] = attempts
                self.transition(item_id, "RUNNING", attempts=attempts)
                if item.get("mode") == "single":
                    ok, data = self.run_single(item, attempts)
                else:
                    ok, data = self.run_dual(item, attempts)
                self.transition(item_id, "ANALYZING", attempts=attempts, dual_status=data.get("dual_status"))
                self.transition(item_id, "SANITIZING", attempts=attempts)
                self.publish_run(item_id, data)
                if ok:
                    self.transition(item_id, "COMPLETE", attempts=attempts, dual_status=data.get("dual_status"))
                    self.update_matrix_summary()
                    self.git_checkpoint(f"mixed-lte6: complete {item_id}")
                    return
                self.last_error = data.get("dual_status") or "run failed"
                if attempts < 3:
                    self.transition(item_id, "RETRY_PENDING", attempts=attempts, last_error=self.last_error)
                    for _ in range(60):
                        if STOP_FILE.exists():
                            return
                        time.sleep(1)
                else:
                    self.transition(item_id, "FAILED_AFTER_RETRIES", attempts=attempts, last_error=self.last_error)
                    self.update_matrix_summary()
                    self.git_checkpoint(f"mixed-lte6: failed {item_id}")
                    return
        except Exception as exc:
            self.last_error = repr(exc)
            attempts += 1
            terminal = "FAILED_AFTER_RETRIES" if attempts >= 3 else "RETRY_PENDING"
            self.transition(item_id, terminal, attempts=attempts, last_error=self.last_error)
            self.git_checkpoint(f"mixed-lte6: {terminal.lower()} {item_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Resume existing campaign state")
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    runner = Runner()
    def handle_signal(signum: int, frame: Any) -> None:
        if signum == signal.SIGINT:
            STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            STOP_FILE.write_text(f"signal {signum} at {now()}\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, lambda signum, frame: raise_system_exit(143))
    signal.signal(signal.SIGINT, handle_signal)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
