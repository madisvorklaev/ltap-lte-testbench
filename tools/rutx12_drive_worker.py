#!/usr/bin/env python3
"""Persistent RUTX12/RB4011 fixed-load drive-test supervisor."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ltap_testbench.drive_tests import rutx12  # noqa: E402

ROOT = REPO / "runtime" / "rutx12-drive"
PUBLIC_ROOT = REPO / "results-public" / "rutx12-drive"
ACTIVE = ROOT / "ACTIVE_SESSION.json"
LOCK = ROOT / "ACTIVE_SESSION.lock"
PRIVATE_IDENTITY = ROOT / ".private-identity"
SSH_KEY = Path.home() / ".ssh" / "elmo_openclaw_ed25519"


@dataclass(frozen=True)
class PathConfig:
    label: str
    source: str
    rut_host: str
    api_base: str
    token_env: str


PATHS = {
    "path-a": PathConfig(
        "path-a",
        rutx12.SOURCE_A,
        "root@192.168.11.1",
        "https://192.168.11.1",
        "RUTX12_A_TOKEN",
    ),
    "path-b": PathConfig(
        "path-b",
        rutx12.SOURCE_B,
        "root@192.168.12.1",
        "https://192.168.12.1",
        "RUTX12_B_TOKEN",
    ),
}

RUT_ENDPOINTS = [
    "/api/unauthorized/status",
    "/api/system/device/status",
    "/api/system/device/usage/status",
    "/api/firmware/modem/status",
    "/api/modems/status",
    "/api/interfaces/status",
    "/api/network/devices/status",
    "/api/ip_routes/ipv4/status",
    "/api/internet_connection/status",
    "/api/failover/status",
    "/api/sim_cards/status",
]

RB4011_EGRESS_RULES = [
    {
        "key": "path-a-correct",
        "path": "path-a",
        "kind": "correct",
        "source": rutx12.SOURCE_A,
        "out_interface": "ether2",
        "comment": "OC RUTX12 VERIFY path-a correct ether2",
    },
    {
        "key": "path-a-wrong",
        "path": "path-a",
        "kind": "wrong",
        "source": rutx12.SOURCE_A,
        "out_interface": "ether3",
        "comment": "OC RUTX12 VERIFY path-a wrong ether3",
    },
    {
        "key": "path-b-correct",
        "path": "path-b",
        "kind": "correct",
        "source": rutx12.SOURCE_B,
        "out_interface": "ether3",
        "comment": "OC RUTX12 VERIFY path-b correct ether3",
    },
    {
        "key": "path-b-wrong",
        "path": "path-b",
        "kind": "wrong",
        "source": rutx12.SOURCE_B,
        "out_interface": "ether2",
        "comment": "OC RUTX12 VERIFY path-b wrong ether2",
    },
]


def slug(value: str) -> str:
    import re

    out = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return out or "rutx12-drive"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    rutx12.atomic_json(path, value)


def now_mono() -> float:
    return time.monotonic()


def command_available(name: str) -> bool:
    if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
        return True
    return any(
        (Path(part) / name).exists() for part in os.environ.get("PATH", "").split(os.pathsep)
    )


class SessionLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(f"Active RUTX12 lock is held: {self.path}") from exc
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{os.getpid()}\n".encode())

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


class Supervisor:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.runtime = ROOT / session_id
        self.public = PUBLIC_ROOT / session_id
        self.stop_event = threading.Event()
        self.load_event = threading.Event()
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.threads: list[threading.Thread] = []
        self.state = read_json(self.runtime / "STATE.json", {})
        self.blockers: list[str] = []
        self.lock = SessionLock(LOCK)

    def add_blocker(self, blocker: str) -> None:
        if blocker not in self.blockers:
            self.blockers.append(blocker)

    def event(self, event_type: str, **extra: Any) -> None:
        rutx12.append_jsonl(
            self.runtime / "events.jsonl",
            {"utc": rutx12.utc_now(), "mono": now_mono(), "type": event_type, **extra},
        )

    def save_state(self, state: str | None = None, phase: str | None = None) -> None:
        if state:
            self.state["state"] = state
        if phase:
            self.state["phase"] = phase
        self.state["updated_utc"] = rutx12.utc_now()
        self.state["worker_pid"] = os.getpid()
        write_json(self.runtime / "STATE.json", self.state)
        write_json(
            self.runtime / "HEARTBEAT.json",
            {
                "session_id": self.session_id,
                "state": self.state.get("state"),
                "phase": self.state.get("phase"),
                "updated_utc": self.state["updated_utc"],
            },
        )

    def start_process(
        self,
        label: str,
        argv: list[str],
        stdout_path: Path,
        stderr_path: Path,
        expected_token: str,
    ) -> subprocess.Popen[str]:
        if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
            argv = fake_process_argv(label, stdout_path, expected_token)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        out = stdout_path.open("w", encoding="utf-8")
        err = stderr_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            argv,
            stdout=out,
            stderr=err,
            text=True,
            start_new_session=True,
        )
        out.close()
        err.close()
        self.processes[label] = proc
        rutx12.append_jsonl(
            self.runtime / "process-ledger.jsonl",
            {
                "utc": rutx12.utc_now(),
                "event": "START",
                "label": label,
                "pid": proc.pid,
                "pgid": os.getpgid(proc.pid),
                "argv": redact_argv(argv),
                "expected_token": expected_token,
            },
        )
        return proc

    def start_thread(self, label: str, target: Any, *args: Any) -> None:
        thread = threading.Thread(target=target, name=f"rutx12-{label}", args=args, daemon=True)
        thread.start()
        self.threads.append(thread)
        self.event("THREAD_STARTED", label=label)

    def start_collectors(self) -> None:
        self.start_thread("heartbeat", self.heartbeat_loop)
        self.start_probes()
        self.start_capture()
        for label, cfg in PATHS.items():
            self.start_logs(label, cfg)
            self.start_thread(f"{label}-rut", self.rut_collector, cfg)
        self.start_thread("gps", self.gps_collector, PATHS["path-a"])
        self.start_thread("rb4011", self.rb_collector)
        self.save_state("RUNNING_COLLECTORS", "PRE_IDLE")

    def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            write_json(
                self.runtime / "HEARTBEAT.json",
                {
                    "session_id": self.session_id,
                    "state": self.state.get("state"),
                    "phase": self.state.get("phase"),
                    "worker_pid": os.getpid(),
                    "updated_utc": rutx12.utc_now(),
                    "owned_process_count": len(
                        [proc for proc in self.processes.values() if proc.poll() is None]
                    ),
                },
            )
            self.stop_event.wait(10.0)

    def start_probes(self) -> None:
        for label, cfg in PATHS.items():
            argv = [
                "ping",
                "-n",
                "-D",
                "-O",
                "-i",
                "0.2",
                "-W",
                "1",
                "-I",
                cfg.source,
                rutx12.SERVER_IPV4,
            ]
            if command_available("ping"):
                self.start_process(
                    f"probe-{label}",
                    argv,
                    self.runtime / "probes" / f"{label}.ping.txt",
                    self.runtime / "probes" / f"{label}.ping.stderr",
                    cfg.source,
                )
            else:
                self.add_blocker("PING_COMMAND_MISSING")

    def start_capture(self) -> None:
        argv = [
            "tcpdump",
            "-i",
            "any",
            "-s",
            "96",
            "-U",
            "-w",
            str(self.runtime / "capture" / "receiver-udp.pcap"),
            "udp",
            "and",
            "host",
            rutx12.SERVER_IPV4,
            "and",
            "portrange",
            "5201-5208",
        ]
        if command_available("tcpdump"):
            self.start_process(
                "packet-capture",
                argv,
                self.runtime / "capture" / "tcpdump.stdout",
                self.runtime / "capture" / "tcpdump.stderr",
                "tcpdump",
            )
        else:
            self.add_blocker("TCPDUMP_COMMAND_MISSING")

    def start_logs(self, label: str, cfg: PathConfig) -> None:
        argv = [*ssh_base(cfg.rut_host), "logread -f"]
        if SSH_KEY.exists() and command_available("ssh"):
            self.start_process(
                f"log-{label}",
                argv,
                self.runtime / "logs" / f"{label}.logread.txt",
                self.runtime / "logs" / f"{label}.logread.stderr",
                cfg.rut_host,
            )
        else:
            self.add_blocker(f"{label.upper()}_LOG_SSH_UNAVAILABLE")

    def rut_collector(self, cfg: PathConfig) -> None:
        router_label = "rut-a" if cfg.label == "path-a" else "rut-b"
        while not self.stop_event.is_set():
            started = sample_start()
            if self.use_ssh_backend(cfg):
                bundle = self.ssh_api_bundle(cfg)
            else:
                bundle = {}
                for endpoint in RUT_ENDPOINTS:
                    bundle[endpoint] = self.api_get(cfg, endpoint)
                modems = rutx12.as_list(bundle.get("/api/modems/status"))
                selected = rutx12.selected_modem([m for m in modems if isinstance(m, dict)])
                selected_id = selected.get("id") if selected else None
                if selected_id:
                    endpoint = f"/api/modems/status/{urllib.parse.quote(str(selected_id), safe='')}"
                    signal_endpoint = (
                        f"/api/modems/signal/status/{urllib.parse.quote(str(selected_id), safe='')}"
                    )
                    bundle[endpoint] = self.api_get(cfg, endpoint)
                    bundle[signal_endpoint] = self.api_get(cfg, signal_endpoint)
            completed = sample_end(started)
            raw = {**completed, "router": router_label, "path": cfg.label, "endpoints": bundle}
            rutx12.append_jsonl(self.runtime / router_label / "raw-api.jsonl", raw)
            normalized = rutx12.normalize_api_bundle(bundle, router_label)
            normalized.update(completed)
            normalized["path"] = cfg.label
            rutx12.append_jsonl(self.runtime / router_label / "modem.jsonl", normalized)
            self.stop_event.wait(1.0)

    def gps_collector(self, cfg: PathConfig) -> None:
        while not self.stop_event.is_set():
            started = sample_start()
            if self.use_ssh_backend(cfg):
                raw = self.ssh_gps_status(cfg)
            else:
                raw = self.api_get(cfg, "/api/gps/position/status")
            completed = sample_end(started)
            rutx12.append_jsonl(
                self.runtime / "gps" / "raw.jsonl",
                {
                    **completed,
                    "router": cfg.label,
                    "endpoint": "/api/gps/position/status",
                    "raw": raw,
                },
            )
            body = raw.get("body") if isinstance(raw, dict) else {}
            parsed = rutx12.normalize_gps(body if isinstance(body, dict) else {})
            parsed.update(completed)
            parsed["backend"] = raw.get("backend") if isinstance(raw, dict) else None
            rutx12.append_jsonl(self.runtime / "gps" / "position.jsonl", parsed)
            self.stop_event.wait(1.0)

    def rb_collector(self) -> None:
        command = (
            "/ip route print detail; /routing rule print detail; "
            '/ip firewall mangle print stats detail where comment~"ELMO|RUTX"; '
            '/interface ethernet print stats detail where name~"ether2|ether3"; '
            "/system resource print"
        )
        while not self.stop_event.is_set():
            started = sample_start()
            result = run_capture([*ssh_base("admin@192.168.88.1"), command], timeout=8)
            rutx12.append_jsonl(
                self.runtime / "rb4011" / "samples.jsonl",
                {**sample_end(started), "result": result},
            )
            self.stop_event.wait(1.0)

    def api_get(self, cfg: PathConfig, endpoint: str) -> dict[str, Any]:
        fixture = os.environ.get("RUTX12_FIXTURE_DIR")
        if fixture:
            return read_fixture(Path(fixture), cfg.label, endpoint)
        if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
            return {"ok": True, "body": fake_api_body(endpoint)}
        token = os.environ.get(cfg.token_env)
        if not token:
            return {"ok": False, "error": "TOKEN_MISSING", "body": None}
        url = cfg.api_base.rstrip("/") + endpoint
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        context = ssl.create_default_context()
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=4, context=context) as response:
                text = response.read().decode("utf-8", errors="replace")
            try:
                body: Any = json.loads(text)
            except json.JSONDecodeError:
                body = {"raw_text": text}
            return {
                "ok": True,
                "status": response.status,
                "duration_s": time.monotonic() - started,
                "body": body,
            }
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"ok": False, "duration_s": time.monotonic() - started, "error": repr(exc)}

    def use_ssh_backend(self, cfg: PathConfig) -> bool:
        return not os.environ.get(cfg.token_env) and SSH_KEY.exists() and command_available("ssh")

    def ssh_api_bundle(self, cfg: PathConfig) -> dict[str, Any]:
        script = r"""
printf '__BOOT_ID__\n'; cat /proc/sys/kernel/random/boot_id 2>/dev/null || true
printf '__UPTIME__\n'; cat /proc/uptime 2>/dev/null || true
printf '__MODEM_STATUS__\n'; ubus call mobifd.modem0 status 2>/dev/null || true
printf '__MODEM_INFO__\n'; ubus call gsm.modem0 info 2>/dev/null || true
printf '__NETWORK_INFO__\n'; ubus call gsm.modem0 get_network_info 2>/dev/null || true
printf '__SERVING_CELL__\n'; ubus call gsm.modem0 get_serving_cell 2>/dev/null || true
printf '__CA_INFO__\n'; ubus call gsm.modem0 get_ca_info 2>/dev/null || true
printf '__PDP_ADDR__\n'; ubus call gsm.modem0 get_pdp_addr_list 2>/dev/null || true
printf '__IFACES__\n'; ubus call network.interface dump 2>/dev/null || true
"""
        result = run_capture([*ssh_base(cfg.rut_host), script], timeout=8)
        sections = parse_marked_sections(result.get("stdout", ""))
        boot_id = (sections.get("BOOT_ID") or "").splitlines()[0:1]
        uptime_text = (sections.get("UPTIME") or "").split()
        uptime = float(uptime_text[0]) if uptime_text and is_float(uptime_text[0]) else None
        modem_status = load_section_json(sections.get("MODEM_STATUS")) or {}
        modem_info = load_section_json(sections.get("MODEM_INFO")) or {}
        network_info = load_section_json(sections.get("NETWORK_INFO")) or {}
        serving_cell = load_section_json(sections.get("SERVING_CELL")) or {}
        ca_info = load_section_json(sections.get("CA_INFO")) or {}
        pdp_addr = load_section_json(sections.get("PDP_ADDR")) or {}
        ifaces = load_section_json(sections.get("IFACES")) or {}
        selected_id = str(modem_status.get("modem_id") or modem_info.get("usb_id") or "modem0")
        modem_body = {
            "data": [
                {
                    "id": selected_id,
                    "modem_id": selected_id,
                    "primary": modem_info.get("primary", True),
                    "data_connected": bool(rutx12.as_list(pdp_addr)),
                    "operator": (modem_info.get("cache") or {}).get("operator"),
                }
            ]
        }
        detail_body = {
            **modem_info,
            **network_info,
            "id": selected_id,
            "modem_id": selected_id,
            "registered": (modem_info.get("cache") or {}).get("reg_stat"),
            "cell_info": rutx12.as_list(serving_cell),
            "ca_info": rutx12.as_list(ca_info),
            "pdp_addr": rutx12.as_list(pdp_addr),
        }
        return {
            "/api/system/device/status": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": {"boot_id": boot_id[0] if boot_id else None, "uptime": uptime},
            },
            "/api/modems/status": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": modem_body,
            },
            f"/api/modems/status/{selected_id}": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": detail_body,
            },
            f"/api/modems/signal/status/{selected_id}": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": (modem_info.get("cache") or {}),
            },
            "/api/interfaces/status": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": ifaces,
            },
            "/api/network/devices/status": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": {"data": []},
            },
            "/api/ip_routes/ipv4/status": {
                "ok": result.get("returncode") == 0,
                "backend": "ssh",
                "body": ifaces,
            },
            "_ssh_result": result,
        }

    def prequalify_ports(self) -> list[tuple[int, int]]:
        qualified: list[tuple[int, int]] = []
        attempts: list[dict[str, Any]] = []
        for ports in rutx12.PORT_PAIRS:
            for orientation, oriented_ports in (
                ("a-b", ports),
                ("b-a", (ports[1], ports[0])),
            ):
                rows = self.run_dual_epoch(
                    oriented_ports,
                    duration_s=10,
                    epoch_id=f"preflight-{ports[0]}-{ports[1]}-{orientation}",
                    ledger_name="preflight-ledger",
                )
                attempt = {
                    "ports": list(ports),
                    "orientation": orientation,
                    "assigned_ports": list(oriented_ports),
                    "joint_classification": rows["joint_classification"],
                    "passed": rows["joint_classification"] == "VALID_DELIVERY",
                }
                attempts.append(attempt)
                if attempt["passed"]:
                    qualified.append(oriented_ports)
        qualified = select_disjoint_assignments(qualified)
        if len(qualified) < 2:
            self.add_blocker("FEWER_THAN_TWO_ORIENTED_ASSIGNMENTS_PREQUALIFIED")
        self.state["qualified_port_pairs"] = qualified
        self.state["qualified_oriented_assignments"] = [
            {"path_a_port": ports[0], "path_b_port": ports[1]} for ports in qualified
        ]
        self.state["preflight_attempts"] = attempts
        write_json(self.runtime / "preflight-attempts.json", attempts)
        self.save_state()
        return qualified

    def run_traffic_for_gate(self, load_s: int, ports: list[tuple[int, int]]) -> None:
        epoch = 0
        traffic_deadline = time.monotonic() + load_s
        partial_after_s = 5
        while (
            not self.stop_event.is_set()
            and time.monotonic() + 10 + partial_after_s < traffic_deadline
        ):
            epoch += 1
            pair = ports[(epoch - 1) % len(ports)] if ports else rutx12.PORT_PAIRS[0]
            self.run_dual_epoch(pair, duration_s=10, epoch_id=f"{epoch:04d}")
        if not self.stop_event.is_set():
            epoch += 1
            pair = ports[(epoch - 1) % len(ports)] if ports else rutx12.PORT_PAIRS[0]
            self.run_dual_epoch(
                pair,
                duration_s=10,
                epoch_id=f"{epoch:04d}",
                partial=True,
                partial_after_s=partial_after_s,
            )

    def run_dual_epoch(
        self,
        ports: tuple[int, int],
        duration_s: int,
        epoch_id: str,
        partial: bool = False,
        partial_after_s: int | None = None,
        ledger_name: str = "epoch-ledger",
    ) -> dict[str, Any]:
        epoch_dir = self.runtime / "traffic" / f"epoch-{epoch_id}"
        epoch_dir.mkdir(parents=True, exist_ok=True)
        assignments = [("path-a", ports[0]), ("path-b", ports[1])]
        before_counters = self.sample_rb_egress_counters(epoch_id, "before")
        processes = []
        start_barrier = time.monotonic() + 0.250
        while time.monotonic() < start_barrier:
            time.sleep(0.001)
        for label, port in assignments:
            cfg = PATHS[label]
            argv = rutx12.build_iperf_argv(rutx12.SERVER_IPV4, port, cfg.source, duration_s)
            path_dir = epoch_dir / label
            path_dir.mkdir(parents=True, exist_ok=True)
            proc = self.start_process(
                f"iperf-{epoch_id}-{label}",
                argv,
                path_dir / "iperf.json",
                path_dir / "iperf.stderr",
                "iperf3",
            )
            processes.append(
                (label, port, argv, path_dir, proc, time.monotonic(), rutx12.utc_now())
            )
        if partial and partial_after_s is not None:
            wait_interruptibly(self.stop_event, partial_after_s)
            for _label, _port, _argv, _path_dir, proc, _started_mono, _started_utc in processes:
                if proc.poll() is None:
                    terminate_process(proc)
        rows: dict[str, Any] = {}
        for label, port, argv, path_dir, proc, started_mono, started_utc in processes:
            timeout = max(2.0, duration_s + 3.0)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                partial = True
                terminate_process(proc)
            completed_mono = time.monotonic()
            completed_utc = rutx12.utc_now()
            text = (path_dir / "iperf.json").read_text(encoding="utf-8", errors="ignore")
            measured_duration = (
                float(duration_s)
                if os.environ.get("RUTX12_FAKE_COMMANDS") == "1"
                else completed_mono - started_mono
            )
            evidence = rutx12.validate_receiver_evidence(
                argv,
                proc.returncode,
                measured_duration,
                text,
            )
            row = {
                "epoch_id": epoch_id,
                "path": label,
                "port": port,
                "argv": redact_argv(argv),
                "started_utc": started_utc,
                "completed_utc": completed_utc,
                "started_mono": started_mono,
                "completed_mono": completed_mono,
                "returncode": proc.returncode,
                "partial": partial,
                "partial_reason": "PARTIAL_STOPPED_BY_GATE" if partial else None,
                **evidence,
            }
            write_json(path_dir / "result.json", row)
            rutx12.append_jsonl(self.runtime / "traffic" / f"{ledger_name}.jsonl", row)
            rows[label] = row
        after_counters = self.sample_rb_egress_counters(epoch_id, "after")
        egress = evaluate_egress_isolation(before_counters, after_counters)
        if not egress["observed"]:
            self.add_blocker("RB4011_EGRESS_ISOLATION_NOT_OBSERVED")
        elif egress["cross_egress"]:
            self.add_blocker("RB4011_CROSS_EGRESS_DETECTED")
        skew = abs(rows["path-a"]["started_mono"] - rows["path-b"]["started_mono"])
        joint = rutx12.classify_epoch(
            rows["path-a"],
            rows["path-b"],
            skew_s=skew,
            cross_egress=bool(egress["cross_egress"]),
            partial=partial,
        )
        out = {
            "epoch_id": epoch_id,
            "joint_classification": joint,
            "start_skew_s": skew,
            "egress_isolation": egress,
        }
        rutx12.append_jsonl(
            self.runtime
            / "traffic"
            / ("joint-epochs.jsonl" if ledger_name == "epoch-ledger" else "preflight-joint.jsonl"),
            out,
        )
        return out

    def sample_rb_egress_counters(self, epoch_id: str, phase: str) -> dict[str, Any]:
        if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
            base = int(time.monotonic() * 1000)
            counters = {
                "path-a": {"correct": base + (100 if phase == "after" else 0), "cross": 0},
                "path-b": {"correct": base + (100 if phase == "after" else 0), "cross": 0},
            }
            row = {"epoch_id": epoch_id, "phase": phase, "observed": True, "counters": counters}
            rutx12.append_jsonl(self.runtime / "rb4011" / "egress-isolation.jsonl", row)
            return row
        result = run_capture([*ssh_base("admin@192.168.88.1"), rb4011_counter_script()], timeout=8)
        counters = parse_rb4011_egress_counters(result.get("stdout", ""))
        row = {
            "epoch_id": epoch_id,
            "phase": phase,
            "observed": bool(counters),
            "counters": counters,
            "result": result,
        }
        rutx12.append_jsonl(self.runtime / "rb4011" / "egress-isolation.jsonl", row)
        return row

    def run_road(self) -> int:
        self.lock.acquire()
        try:
            self.event("ROAD_SUPERVISOR_STARTED")
            self.ensure_rb4011_egress_rules()
            self.start_collectors()
            ports = self.state.get("qualified_port_pairs") or rutx12.PORT_PAIRS[:2]
            normalized_ports = [tuple(pair) for pair in ports if isinstance(pair, list | tuple)]
            self.save_state("PRE_IDLE", "PRE_IDLE")
            while not self.stop_event.is_set():
                if (self.runtime / "STOP_REQUESTED").exists():
                    self.event("STOP_FILE_OBSERVED")
                    break
                state = read_json(self.runtime / "STATE.json", {})
                phase = state.get("phase")
                self.state.update(state)
                if phase in {"LOADED_PARKED", "MOVING_LOADED", "ARRIVED_LOADED"}:
                    self.run_traffic_for_road(normalized_ports)
                else:
                    self.stop_event.wait(1.0)
            self.finalize("ANALYZING")
            return 0
        finally:
            self.lock.release()

    def run_traffic_for_road(self, ports: list[tuple[int, int]]) -> None:
        epoch = int(self.state.get("road_epoch", 0)) + 1
        pair = ports[(epoch - 1) % len(ports)] if ports else rutx12.PORT_PAIRS[0]
        self.run_dual_epoch(pair, duration_s=10, epoch_id=f"road-{epoch:04d}")
        self.state["road_epoch"] = epoch
        self.save_state()

    def ensure_rb4011_egress_rules(self) -> None:
        if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
            self.event("RB4011_EGRESS_RULES_FAKE_READY")
            return
        result = run_capture(
            [*ssh_base("admin@192.168.88.1"), rb4011_rule_install_script()], timeout=15
        )
        rutx12.append_jsonl(
            self.runtime / "rb4011" / "egress-rule-setup.jsonl",
            {"utc": rutx12.utc_now(), "result": result, "rules": RB4011_EGRESS_RULES},
        )
        if result.get("returncode") != 0:
            self.add_blocker("RB4011_EGRESS_RULE_SETUP_FAILED")

    def ssh_gps_status(self, cfg: PathConfig) -> dict[str, Any]:
        if os.environ.get("RUTX12_FAKE_COMMANDS") == "1":
            return {"ok": True, "backend": "ssh", "body": fake_api_body("/api/gps/position/status")}
        script = r"""
printf '__GPS_UBUS_STATUS__\n'; ubus call gps status 2>/dev/null || true
printf '__GPS_UBUS_POSITION__\n'; ubus call gps position 2>/dev/null || true
printf '__GPS_GPSD__\n'; ubus call gpsd info 2>/dev/null || true
printf '__GPS_GPSCTL__\n'; gpsctl -ix 2>/dev/null || true
"""
        result = run_capture([*ssh_base(cfg.rut_host), script], timeout=8)
        sections = parse_marked_sections(result.get("stdout", ""))
        body = parse_ssh_gps_sections(sections)
        ok = result.get("returncode") == 0 and bool(body)
        return {
            "ok": ok,
            "backend": "ssh",
            "body": body or {},
            "error": None if ok else "GPS_QUERY_NO_PARSEABLE_POSITION",
            "ssh_result": result,
        }

    def run_gate(self, idle_s: int, load_s: int, post_s: int) -> int:
        self.lock.acquire()
        try:
            if idle_s < 300 or load_s < 300 or post_s < 300:
                self.add_blocker("FULL_15_MIN_STATIONARY_GATE_NOT_YET_RUN")
            self.event("GATE_STARTED", idle_s=idle_s, load_s=load_s, post_s=post_s)
            self.ensure_rb4011_egress_rules()
            self.start_collectors()
            self.save_state("PRE_IDLE", "PRE_IDLE")
            wait_interruptibly(self.stop_event, idle_s)
            ports = self.prequalify_ports()
            self.save_state("LOADED_PARKED", "LOADED_PARKED")
            self.event("LOAD_STARTED")
            self.run_traffic_for_gate(load_s, ports)
            self.event("LOAD_STOPPED", deliberate_mid_epoch_stop=True)
            self.save_state("POST_IDLE", "POST_IDLE")
            wait_interruptibly(self.stop_event, post_s)
            self.event("GATE_FINISHED")
            self.finalize("ANALYZING")
            return 0 if not self.blockers else 2
        finally:
            self.lock.release()

    def finalize(self, state: str = "ANALYZING") -> None:
        self.save_state(state)
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3)
        self.cleanup_processes()
        summary = analyze_session(self.runtime, self.public, self.blockers)
        self.state["summary"] = summary
        self.state["state"] = summary["gate_result_state"]
        self.event("FINAL_STATE_READY", gate_result_state=summary["gate_result_state"])
        self.save_state()
        rutx12.write_checksums(self.runtime)
        rutx12.write_checksums(self.public)
        if ACTIVE.exists():
            active = read_json(ACTIVE, {})
            if active.get("session_id") == self.session_id:
                ACTIVE.unlink()

    def cleanup_processes(self) -> None:
        for label, proc in list(self.processes.items()):
            if proc.poll() is None:
                terminate_process(proc)
            rutx12.append_jsonl(
                self.runtime / "process-ledger.jsonl",
                {
                    "utc": rutx12.utc_now(),
                    "event": "STOP",
                    "label": label,
                    "pid": proc.pid,
                    "returncode": proc.returncode,
                },
            )
        orphaned = []
        for label, proc in self.processes.items():
            if Path(f"/proc/{proc.pid}").exists():
                orphaned.append({"label": label, "pid": proc.pid})
        write_json(self.runtime / "orphan-check.json", {"orphaned": orphaned})
        if orphaned:
            self.blockers.append("SESSION_OWNED_ORPHANS_REMAIN")


def sample_start() -> dict[str, Any]:
    return {"sample_started_utc": rutx12.utc_now(), "sample_started_mono": time.monotonic()}


def sample_end(started: dict[str, Any]) -> dict[str, Any]:
    return {
        **started,
        "sample_completed_utc": rutx12.utc_now(),
        "sample_completed_mono": time.monotonic(),
    }


def wait_interruptibly(stop_event: threading.Event, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not stop_event.is_set() and time.monotonic() < deadline:
        stop_event.wait(min(1.0, deadline - time.monotonic()))


def terminate_process(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=4)
    except Exception:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=4)
            except Exception:
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait(timeout=4)


def fake_process_argv(label: str, stdout_path: Path, expected_token: str) -> list[str]:
    if expected_token == "iperf3":
        payload = {
            "end": {
                "sum_sent": {
                    "sender": True,
                    "seconds": 10.0,
                    "bits_per_second": rutx12.REQUIRED_RATE_BPS,
                },
                "sum_received": {
                    "sender": False,
                    "seconds": 10.0,
                    "bits_per_second": 4_950_000,
                    "lost_packets": 1,
                    "packets": 4167,
                    "lost_percent": 0.024,
                    "jitter_ms": 2.1,
                },
            }
        }
        return [
            sys.executable,
            "-c",
            (f"import json,time;time.sleep(0.02);print(json.dumps({json.dumps(payload)}))"),
        ]
    if label.startswith("probe-"):
        return [
            sys.executable,
            "-c",
            (
                "import time,sys;"
                "i=1\n"
                "try:\n"
                "  while True:\n"
                "    print("
                "f'64 bytes from 217.18.95.142: icmp_seq={i} ttl=55 time=45.0 ms',"
                " flush=True);"
                "    i+=1; time.sleep(0.2)\n"
                "except KeyboardInterrupt:\n"
                "  sys.exit(0)\n"
            ),
        ]
    if label == "packet-capture":
        return [sys.executable, "-c", "import time; time.sleep(3600)"]
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    return [sys.executable, "-c", "import time; time.sleep(3600)"]


def read_fixture(root: Path, label: str, endpoint: str) -> dict[str, Any]:
    name = endpoint.strip("/").replace("/", "__")
    path = root / label / f"{name}.json"
    if not path.exists():
        return {"ok": False, "error": "FIXTURE_MISSING", "body": None, "fixture": str(path)}
    return {"ok": True, "body": read_json(path, None), "fixture": str(path)}


def parse_marked_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("__") and line.endswith("__"):
            current = line.strip("_")
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def load_section_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def fake_api_body(endpoint: str) -> Any:
    if endpoint == "/api/system/device/status":
        return {"boot_id": "boot-pseudonymous-fixture", "uptime": 12345}
    if endpoint == "/api/modems/status":
        return {
            "data": [
                {"id": "modem0", "primary": "0", "data_connected": "0"},
                {"id": "modem1", "primary": "1", "data_connected": "1", "operator": "fixture"},
            ]
        }
    if endpoint.startswith("/api/modems/status/"):
        return {
            "id": "modem1",
            "primary": "1",
            "registered": "registered",
            "data_connected": "1",
            "rat": "LTE",
            "band": "B3",
            "cell_info": [{"pci": 123, "earfcn": 1300}],
            "ca_signal": [{"band": "B20", "rsrp": "-95"}],
        }
    if endpoint.startswith("/api/modems/signal/status/"):
        return {"rsrp": "-91 dBm", "rsrq": "-9 dB", "sinr": "12 dB"}
    if endpoint == "/api/interfaces/status":
        return {"data": [{"id": "mob1s1a1", "proto": "mobile", "ipv4": "10.0.0.2"}]}
    if endpoint == "/api/network/devices/status":
        return {"data": [{"id": "wwan0", "up": "1"}]}
    if endpoint == "/api/ip_routes/ipv4/status":
        return {"data": [{"target": "0.0.0.0/0", "interface": "mob1s1a1"}]}
    if endpoint == "/api/gps/position/status":
        return {
            "valid": "1",
            "lat": 59.400001,
            "lon": 24.700001,
            "speed": 0,
            "course": 0,
            "satellites": 12,
            "hdop": 0.8,
        }
    return {}


def select_disjoint_assignments(assignments: list[tuple[int, int]]) -> list[tuple[int, int]]:
    selected: list[tuple[int, int]] = []
    for assignment in assignments:
        ports = set(assignment)
        if selected and any(ports & set(existing) for existing in selected):
            continue
        selected.append(assignment)
        if len(selected) >= 2:
            return selected
    return selected


def rb4011_rule_install_script() -> str:
    lines = []
    for rule in RB4011_EGRESS_RULES:
        comment = rule["comment"]
        command = (
            f':if ([:len [/ip firewall mangle find where comment="{comment}"]] = 0) do={{'
            "/ip firewall mangle add chain=forward action=passthrough "
            f"src-address={rule['source']} out-interface={rule['out_interface']} "
            f'passthrough=yes comment="{comment}"'
            "}"
        )
        lines.append(command)
    lines.append(rb4011_counter_script())
    return "; ".join(lines)


def rb4011_counter_script() -> str:
    lines = [
        f':foreach i in=[/ip firewall mangle find where comment="{rule["comment"]}"] do={{'
        f':put ("{rule["comment"]} packets=".[/ip firewall mangle get $i packets].'
        '" bytes=".[/ip firewall mangle get $i bytes])}'
        for rule in RB4011_EGRESS_RULES
    ]
    return "; ".join(lines)


def parse_rb4011_egress_counters(text: str) -> dict[str, dict[str, int]]:
    counters: dict[str, dict[str, int]] = {
        "path-a": {"correct": 0, "cross": 0},
        "path-b": {"correct": 0, "cross": 0},
    }
    for line in text.splitlines():
        lower = line.lower()
        current = None
        key = None
        if "oc rutx12 verify path-a correct" in lower:
            current, key = "path-a", "correct"
        elif "oc rutx12 verify path-a wrong" in lower:
            current, key = "path-a", "cross"
        elif "oc rutx12 verify path-b correct" in lower:
            current, key = "path-b", "correct"
        elif "oc rutx12 verify path-b wrong" in lower:
            current, key = "path-b", "cross"
        match = re_search_counter(line)
        if current is not None and key is not None and match is not None:
            counters[current][key] = max(counters[current].get(key, 0), match)
    return counters if any(any(values.values()) for values in counters.values()) else {}


def re_search_counter(line: str) -> int | None:
    import re

    for pattern in (r"\bpackets=(\d+)", r"\bpacket[s]?:\s*(\d+)", r"\bbytes=(\d+)"):
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def evaluate_egress_isolation(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    before_counters = before.get("counters") if isinstance(before, dict) else {}
    after_counters = after.get("counters") if isinstance(after, dict) else {}
    if not isinstance(before_counters, dict) or not isinstance(after_counters, dict):
        return {"observed": False, "cross_egress": False, "deltas": {}}
    deltas: dict[str, dict[str, int | None]] = {}
    observed = True
    cross_egress = False
    for path in ("path-a", "path-b"):
        b = before_counters.get(path)
        a = after_counters.get(path)
        if not isinstance(b, dict) or not isinstance(a, dict):
            observed = False
            continue
        correct, _ = rutx12.counter_delta(int(b.get("correct", 0)), int(a.get("correct", 0)))
        cross, _ = rutx12.counter_delta(int(b.get("cross", 0)), int(a.get("cross", 0)))
        deltas[path] = {"correct": correct, "cross": cross}
        if correct is None or correct <= 0:
            observed = False
        if cross is not None and cross > 0:
            cross_egress = True
    return {"observed": observed, "cross_egress": cross_egress, "deltas": deltas}


def parse_ssh_gps_sections(sections: dict[str, str]) -> dict[str, Any]:
    for name in ("GPS_UBUS_POSITION", "GPS_UBUS_STATUS", "GPS_GPSD"):
        body = load_section_json(sections.get(name))
        if isinstance(body, dict):
            normalized = extract_gps_candidate(body)
            if normalized:
                return normalized
    text = sections.get("GPS_GPSCTL") or ""
    return parse_gpsctl_text(text)


def extract_gps_candidate(body: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [body]
    for key in ("position", "gps", "data", "status"):
        value = body.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        lat = candidate.get("lat") if "lat" in candidate else candidate.get("latitude")
        lon = candidate.get("lon") if "lon" in candidate else candidate.get("longitude")
        if lat is None or lon is None:
            continue
        return {
            "valid": candidate.get("valid", candidate.get("fix", True)),
            "lat": lat,
            "lon": lon,
            "speed": candidate.get("speed") or candidate.get("speed_mps"),
            "course": candidate.get("course") or candidate.get("bearing"),
            "satellites": candidate.get("satellites") or candidate.get("sats"),
            "hdop": candidate.get("hdop") or candidate.get("accuracy"),
        }
    return None


def parse_gpsctl_text(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    out: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace(" ", "_")
        out[key] = value.strip()
    if "latitude" in out and "longitude" in out:
        out["lat"] = out["latitude"]
        out["lon"] = out["longitude"]
        out.setdefault("valid", True)
    return out


def run_capture(argv: list[str], timeout: float | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return {
            "argv": redact_argv(argv),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": time.monotonic() - started,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": redact_argv(argv),
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration_s": time.monotonic() - started,
            "timeout": True,
        }


def redact_argv(argv: list[str]) -> list[str]:
    return ["<ssh-key>" if item == str(SSH_KEY) else item for item in argv]


def ssh_base(host: str) -> list[str]:
    return [
        "ssh",
        "-i",
        str(SSH_KEY),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        host,
    ]


def create_session(args: argparse.Namespace, validation: bool) -> str:
    ROOT.mkdir(parents=True, exist_ok=True)
    PUBLIC_ROOT.mkdir(parents=True, exist_ok=True)
    active = read_json(ACTIVE, {})
    if isinstance(active, dict) and active.get("session_id"):
        active_state = active.get("state")
        if active_state not in {"READY_FOR_ROAD", "BLOCKED_STATIONARY_GATE", "COMPLETE"}:
            raise SystemExit(f"Active RUTX12 session already exists: {active['session_id']}")
    lock = SessionLock(LOCK)
    lock.acquire()
    lock.release()
    session_id = (
        f"rutx12-drive-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{slug(args.name)}"
    )
    runtime = ROOT / session_id
    public = PUBLIC_ROOT / session_id
    for path in (
        runtime / "baseline",
        runtime / "raw",
        runtime / "gps",
        runtime / "rut-a",
        runtime / "rut-b",
        runtime / "path-a",
        runtime / "path-b",
        runtime / "rb4011",
        runtime / "probes",
        runtime / "traffic",
        runtime / "logs",
        runtime / "capture",
        runtime / "derived",
        public,
    ):
        path.mkdir(parents=True, exist_ok=True)
    traffic_contract = {
        "server_ipv4": rutx12.SERVER_IPV4,
        "rate_bps_per_path": rutx12.REQUIRED_RATE_BPS,
        "payload_bytes": rutx12.REQUIRED_PAYLOAD_BYTES,
        "epoch_seconds": 10,
        "sources": {"path-a": rutx12.SOURCE_A, "path-b": rutx12.SOURCE_B},
        "port_pairs": rutx12.PORT_PAIRS,
    }
    code_commit = run_capture(["git", "rev-parse", "HEAD"], timeout=5)["stdout"].strip()
    dirty_digest = rutx12.stable_hash(
        run_capture(["git", "status", "--short", "--untracked-files=no"], timeout=5)["stdout"]
    )
    gate_fingerprint = rutx12.stable_hash(
        {
            "test_code_commit": code_commit,
            "dirty_state_digest": dirty_digest,
            "traffic": traffic_contract,
        }
    )
    manifest = {
        "schema_version": rutx12.SCHEMA_VERSION,
        "session_id": session_id,
        "route_id": getattr(args, "route_id", "stationary-gate"),
        "direction": getattr(args, "direction", "stationary"),
        "created_utc": rutx12.utc_now(),
        "validation_only": validation,
        "pinned_base_commit": rutx12.PINNED_BASE_COMMIT,
        "test_code_commit": code_commit,
        "dirty_state_digest": dirty_digest,
        "gate_fingerprint": gate_fingerprint,
        "private_identity_map": str(PRIVATE_IDENTITY),
        "traffic": traffic_contract,
    }
    write_json(runtime / "manifest.json", manifest)
    state = {
        "session_id": session_id,
        "state": "PRESTART",
        "phase": "PRESTART",
        "created_utc": manifest["created_utc"],
        "runtime_dir": str(runtime),
        "public_dir": str(public),
        "validation_only": validation,
    }
    write_json(runtime / "STATE.json", state)
    write_json(ACTIVE, state)
    rutx12.append_jsonl(
        runtime / "events.jsonl", {"utc": rutx12.utc_now(), "type": "SESSION_CREATED"}
    )
    return session_id


def active_session_id() -> str:
    active = read_json(ACTIVE, {})
    sid = active.get("session_id")
    if not isinstance(sid, str):
        raise SystemExit("No active RUTX12 drive session.")
    return sid


def validate_cmd(args: argparse.Namespace) -> int:
    session_id = create_session(args, validation=True)
    supervisor = Supervisor(session_id)
    install_signal_handlers(supervisor)
    rc = supervisor.run_gate(args.idle_seconds, args.load_seconds, args.post_seconds)
    summary = read_json(supervisor.public / "summary.json", {})
    print(summary["ready_line"])
    return rc


def start_cmd(args: argparse.Namespace) -> int:
    gate_dir = ROOT / args.gate_session_id
    gate_state = read_json(gate_dir / "STATE.json", {})
    gate_summary = read_json(PUBLIC_ROOT / args.gate_session_id / "summary.json", {})
    gate_manifest = read_json(gate_dir / "manifest.json", {})
    if gate_state.get("state") != "READY_FOR_ROAD" or not gate_summary.get("gate_passed"):
        raise SystemExit("Road start blocked: stationary gate has not passed.")
    if not gate_summary.get("road_gps_ready"):
        raise SystemExit("Road start blocked: five outdoor minutes of fresh GPS fixes are missing.")
    verify_problems = verify_session(gate_dir, PUBLIC_ROOT / args.gate_session_id)
    if verify_problems:
        raise SystemExit(
            "Road start blocked: gate verification failed: " + "; ".join(verify_problems)
        )
    if not args.departure_authorized_by:
        raise SystemExit("Road start blocked: explicit departure authorization missing.")
    current_fingerprint = rutx12.stable_hash(
        {
            "test_code_commit": run_capture(["git", "rev-parse", "HEAD"], timeout=5)[
                "stdout"
            ].strip(),
            "dirty_state_digest": rutx12.stable_hash(
                run_capture(["git", "status", "--short", "--untracked-files=no"], timeout=5)[
                    "stdout"
                ]
            ),
            "traffic": {
                "server_ipv4": rutx12.SERVER_IPV4,
                "rate_bps_per_path": rutx12.REQUIRED_RATE_BPS,
                "payload_bytes": rutx12.REQUIRED_PAYLOAD_BYTES,
                "epoch_seconds": 10,
                "sources": {"path-a": rutx12.SOURCE_A, "path-b": rutx12.SOURCE_B},
                "port_pairs": rutx12.PORT_PAIRS,
            },
        }
    )
    if gate_manifest.get("gate_fingerprint") != current_fingerprint:
        raise SystemExit("Road start blocked: code/config fingerprint differs from passed gate.")
    session_id = create_session(args, validation=False)
    state_path = ROOT / session_id / "STATE.json"
    state = read_json(state_path, {})
    state.update(
        {
            "state": "PRE_IDLE",
            "phase": "PRE_IDLE",
            "gate_session_id": args.gate_session_id,
            "departure_authorized_by": args.departure_authorized_by,
            "qualified_port_pairs": gate_summary.get("qualified_port_pairs", []),
            "qualified_oriented_assignments": gate_summary.get(
                "qualified_oriented_assignments", []
            ),
            "gate_fingerprint": gate_manifest.get("gate_fingerprint"),
        }
    )
    write_json(state_path, state)
    write_json(ACTIVE, state)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "supervise-road",
            "--session-id",
            session_id,
        ],
        stdout=(ROOT / session_id / "logs" / "supervisor.stdout").open("w", encoding="utf-8"),
        stderr=(ROOT / session_id / "logs" / "supervisor.stderr").open("w", encoding="utf-8"),
        start_new_session=True,
        text=True,
    )
    state["worker_pid"] = proc.pid
    write_json(state_path, state)
    write_json(ACTIVE, state)
    rutx12.append_jsonl(
        ROOT / session_id / "process-ledger.jsonl",
        {
            "utc": rutx12.utc_now(),
            "event": "START",
            "label": "road-supervisor",
            "pid": proc.pid,
            "pgid": os.getpgid(proc.pid),
            "argv": [
                "python",
                "tools/rutx12_drive_worker.py",
                "supervise-road",
                "--session-id",
                session_id,
            ],
            "expected_token": "rutx12-road-supervisor",
        },
    )
    print(f"RUTX12 road session started: {session_id}")
    return 0


def load_start_cmd(_args: argparse.Namespace) -> int:
    sid = active_session_id()
    state_path = ROOT / sid / "STATE.json"
    state = read_json(state_path, {})
    state["state"] = "LOADED_PARKED"
    state["phase"] = "LOADED_PARKED"
    write_json(state_path, state)
    rutx12.append_jsonl(
        ROOT / sid / "events.jsonl", {"utc": rutx12.utc_now(), "type": "LOAD_STARTED"}
    )
    print("Load marked started.")
    return 0


def load_stop_cmd(args: argparse.Namespace) -> int:
    sid = active_session_id()
    state_path = ROOT / sid / "STATE.json"
    state = read_json(state_path, {})
    state["state"] = "POST_IDLE"
    state["phase"] = "POST_IDLE"
    state["post_idle_s"] = args.post_idle
    write_json(state_path, state)
    rutx12.append_jsonl(
        ROOT / sid / "events.jsonl", {"utc": rutx12.utc_now(), "type": "LOAD_STOPPED"}
    )
    print("Load marked stopped.")
    return 0


def mark_cmd(args: argparse.Namespace) -> int:
    sid = active_session_id()
    rutx12.append_jsonl(
        ROOT / sid / "events.jsonl",
        {"utc": rutx12.utc_now(), "type": "HUMAN_MARK", "label": args.label},
    )
    print(f"Marked: {args.label}")
    return 0


def status_cmd(_args: argparse.Namespace) -> int:
    sid = active_session_id()
    print((ROOT / sid / "STATE.json").read_text(encoding="utf-8"))
    return 0


def stop_cmd(_args: argparse.Namespace) -> int:
    sid = active_session_id()
    runtime = ROOT / sid
    (runtime / "STOP_REQUESTED").write_text(rutx12.utc_now() + "\n", encoding="utf-8")
    state = read_json(runtime / "STATE.json", {})
    pid = state.get("worker_pid")
    if isinstance(pid, int) and Path(f"/proc/{pid}").exists():
        os.kill(pid, signal.SIGTERM)
    print(f"Stop requested: {sid}")
    return 0


def supervise_road_cmd(args: argparse.Namespace) -> int:
    supervisor = Supervisor(args.session_id)
    install_signal_handlers(supervisor)
    return supervisor.run_road()


def analyze_cmd(args: argparse.Namespace) -> int:
    runtime = ROOT / args.session_id
    public = PUBLIC_ROOT / args.session_id
    summary = analyze_session(runtime, public, [])
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def verify_cmd(args: argparse.Namespace) -> int:
    runtime = ROOT / args.session_id
    public = PUBLIC_ROOT / args.session_id
    problems = verify_session(runtime, public)
    summary = read_json(public / "summary.json", {})
    print(
        json.dumps(
            {"session_id": args.session_id, "problems": problems, "summary": summary}, indent=2
        )
    )
    return 0 if not problems else 1


def recompute_overnight_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(rutx12.recompute_overnight_soak(Path(args.run_dir)), indent=2, sort_keys=True))
    return 0


def analyze_session(runtime: Path, public: Path, blockers: list[str]) -> dict[str, Any]:
    public.mkdir(parents=True, exist_ok=True)
    gps_rows = rutx12.load_jsonl(runtime / "gps" / "position.jsonl")
    path_rows = {
        "path-a": rutx12.load_jsonl(runtime / "rut-a" / "modem.jsonl"),
        "path-b": rutx12.load_jsonl(runtime / "rut-b" / "modem.jsonl"),
    }
    epoch_rows = rutx12.load_jsonl(runtime / "traffic" / "epoch-ledger.jsonl")
    joint_rows = rutx12.load_jsonl(runtime / "traffic" / "joint-epochs.jsonl")
    preflight_raw = read_json(runtime / "preflight-attempts.json", [])
    preflight_rows = preflight_raw if isinstance(preflight_raw, list) else []
    valid = [r for r in epoch_rows if r.get("classification") == "VALID_DELIVERY"]
    invalid = [r for r in epoch_rows if r.get("classification") == "INFRASTRUCTURE_INVALID"]
    unknown = [
        r for r in epoch_rows if r.get("classification") == "UNATTRIBUTED_DELIVERY_UNMEASURED"
    ]
    partial = [r for r in epoch_rows if r.get("partial")]
    usable = [r for r in valid if r.get("quality") == "USABLE_DELIVERY"]
    impaired = [r for r in valid if r.get("quality") == "IMPAIRED_DELIVERY"]
    gps_valid = [r for r in gps_rows if r.get("valid")]
    dual_valid = [r for r in joint_rows if r.get("joint_classification") == "VALID_DELIVERY"]
    dual_usable = count_dual_usable(epoch_rows)
    qualified_port_pairs = read_json(runtime / "STATE.json", {}).get("qualified_port_pairs", [])
    qualified_oriented = read_json(runtime / "STATE.json", {}).get(
        "qualified_oriented_assignments", []
    )
    egress_ok = (
        all(
            isinstance(row.get("egress_isolation"), dict)
            and row["egress_isolation"].get("observed") is True
            and row["egress_isolation"].get("cross_egress") is False
            for row in joint_rows
        )
        if joint_rows
        else False
    )
    telemetry_ok = {
        path: [
            row
            for row in rows
            if row.get("boot_id")
            and row.get("registered") is True
            and row.get("data_connected") is True
            and row.get("selected_mobile_ipv4_present") is True
            and row.get("default_route_present") is True
        ]
        for path, rows in path_rows.items()
    }
    state = read_json(runtime / "STATE.json", {})
    orphan_check = read_json(runtime / "orphan-check.json", {})
    orphaned = orphan_check.get("orphaned") if isinstance(orphan_check, dict) else None
    if orphaned:
        blockers.append("SESSION_OWNED_ORPHANS_REMAIN")
    traffic_phases = raw_phase_durations(runtime)
    gps_quality = gps_readiness(gps_rows)
    telemetry = {path: telemetry_metrics(rows) for path, rows in path_rows.items()}
    ping = {
        "path-a": rutx12.account_ping(
            (runtime / "probes" / "path-a.ping.txt")
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
            if (runtime / "probes" / "path-a.ping.txt").exists()
            else []
        ),
        "path-b": rutx12.account_ping(
            (runtime / "probes" / "path-b.ping.txt")
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
            if (runtime / "probes" / "path-b.ping.txt").exists()
            else []
        ),
    }
    enough_raw_evidence = (
        len(joint_rows) > 0
        and len(epoch_rows) > 0
        and all(len(rows) > 0 for rows in path_rows.values())
        and len(gps_rows) > 0
    )
    blockers = list(dict.fromkeys(blockers))
    if (
        len(qualified_port_pairs) < 2
        and "FEWER_THAN_TWO_ORIENTED_ASSIGNMENTS_PREQUALIFIED" not in blockers
    ):
        blockers.append("FEWER_THAN_TWO_ORIENTED_ASSIGNMENTS_PREQUALIFIED")
    if joint_rows and not egress_ok and "RB4011_EGRESS_ISOLATION_FAILED" not in blockers:
        blockers.append("RB4011_EGRESS_ISOLATION_FAILED")
    blockers = list(dict.fromkeys(blockers))
    gate_passed = (
        not blockers
        and enough_raw_evidence
        and len(dual_valid) / len(joint_rows) >= 0.80
        and len(partial) > 0
        and all(len(telemetry_ok[path]) / len(path_rows[path]) >= 0.95 for path in path_rows)
    )
    classification = "RUTX12_MOVING_TEST_VALID" if gate_passed else "RUTX12_MOVING_TEST_INVALID"
    ready_line = (
        "READY FOR RUTX12 MOVING TEST: YES"
        if gate_passed
        else (
            "READY FOR RUTX12 MOVING TEST: NO - "
            f"{first_blocker(blockers, joint_rows, epoch_rows, partial, path_rows, telemetry_ok)}"
        )
    )
    summary = {
        "session_id": runtime.name,
        "classification": classification,
        "gate_passed": gate_passed,
        "gate_result_state": "READY_FOR_ROAD" if gate_passed else "BLOCKED_STATIONARY_GATE",
        "ready_line": ready_line,
        "valid_receiver_epochs": len(valid),
        "invalid_receiver_epochs": len(invalid),
        "unknown_receiver_epochs": len(unknown),
        "usable_receiver_epochs": len(usable),
        "impaired_receiver_epochs": len(impaired),
        "attempted_path_epochs": len(epoch_rows),
        "attempted_dual_epochs": len(joint_rows),
        "valid_dual_epochs": len(dual_valid),
        "usable_dual_epochs": dual_usable,
        "simultaneous_usable_fraction": (dual_usable / len(dual_valid) if dual_valid else None),
        "gps_valid_fixes": len(gps_valid),
        "gps_samples": len(gps_rows),
        "road_gps_ready": gps_quality["road_ready"],
        "gps_valid_fix_rate": gps_quality["valid_fix_rate"],
        "gps_max_gap_s": gps_quality["max_gap_s"],
        "gps_required_for_stationary_gate": False,
        "gps_limitation": "GPS_UNAVAILABLE_OR_NO_FIX" if gps_rows and not gps_valid else None,
        "telemetry_ok_samples": {path: len(rows) for path, rows in telemetry_ok.items()},
        "telemetry_samples": {path: len(rows) for path, rows in path_rows.items()},
        "telemetry_metrics": telemetry,
        "ping": ping,
        "qualified_port_pairs": qualified_port_pairs,
        "qualified_oriented_assignments": qualified_oriented,
        "preflight_attempts": preflight_rows,
        "egress_isolation_ok": egress_ok,
        "device_config_fingerprint": device_config_fingerprint(path_rows, state),
        "blockers": blockers,
        "traffic_phases": traffic_phases,
        "orphaned_processes": orphaned or [],
        "state_before_analysis": state.get("state"),
        "fixed_rate_iperf_not_gcc_video": True,
    }
    write_json(runtime / "derived" / "joint-metrics.json", summary)
    write_json(public / "summary.json", summary)
    write_json(public / "joint-metrics.json", summary)
    write_json(public / "events.json", rutx12.load_jsonl(runtime / "events.jsonl"))
    write_public_manifest(runtime, public)
    write_epoch_ledger(public, epoch_rows)
    write_report(public, summary)
    return summary


def first_blocker(
    blockers: list[str],
    joint_rows: list[dict[str, Any]],
    epoch_rows: list[dict[str, Any]],
    partial: list[dict[str, Any]],
    path_rows: dict[str, list[dict[str, Any]]],
    telemetry_ok: dict[str, list[dict[str, Any]]],
) -> str:
    if blockers:
        return blockers[0]
    if not joint_rows:
        return "ZERO_MEASURED_EPOCHS"
    if not epoch_rows:
        return "ZERO_PATH_EPOCHS"
    if not partial:
        return "PARTIAL_STOP_NOT_PRESERVED"
    for path, rows in path_rows.items():
        if not rows:
            return f"{path.upper()}_TELEMETRY_MISSING"
        if len(telemetry_ok[path]) / len(rows) < 0.95:
            return f"{path.upper()}_TELEMETRY_CONTINUITY_FAILED"
    dual_valid = [r for r in joint_rows if r.get("joint_classification") == "VALID_DELIVERY"]
    if len(dual_valid) / len(joint_rows) < 0.80:
        return "DUAL_RECEIVER_VALID_RATE_BELOW_80_PERCENT"
    return "GATE_CRITERIA_NOT_MET"


def count_dual_usable(epoch_rows: list[dict[str, Any]]) -> int:
    by_epoch: dict[str, dict[str, dict[str, Any]]] = {}
    for row in epoch_rows:
        epoch = str(row.get("epoch_id"))
        path = str(row.get("path"))
        by_epoch.setdefault(epoch, {})[path] = row
    count = 0
    for paths in by_epoch.values():
        if (
            paths.get("path-a", {}).get("quality") == "USABLE_DELIVERY"
            and paths.get("path-b", {}).get("quality") == "USABLE_DELIVERY"
        ):
            count += 1
    return count


def gps_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row.get("valid")]
    rate = len(valid) / len(rows) if rows else 0.0
    gaps = []
    previous: float | None = None
    for row in valid:
        mono = row.get("sample_completed_mono") or row.get("sample_started_mono")
        if isinstance(mono, int | float):
            if previous is not None:
                gaps.append(float(mono) - previous)
            previous = float(mono)
    max_gap = max(gaps) if gaps else None
    span = (
        float(valid[-1].get("sample_completed_mono") or 0)
        - float(valid[0].get("sample_completed_mono") or 0)
        if len(valid) >= 2
        else 0.0
    )
    return {
        "road_ready": bool(rows)
        and rate >= 0.95
        and span >= 300.0
        and (max_gap is None or max_gap <= 3.0),
        "valid_fix_rate": rate,
        "max_gap_s": max_gap,
        "valid_span_s": span,
    }


def telemetry_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = []
    boot_ids = {row.get("boot_id") for row in rows if row.get("boot_id")}
    registration_outages = count_false_runs(rows, "registered")
    data_outages = count_false_runs(rows, "data_connected")
    address_outages = count_false_runs(rows, "selected_mobile_ipv4_present")
    route_outages = count_false_runs(rows, "default_route_present")
    previous: float | None = None
    for row in rows:
        mono = row.get("sample_completed_mono") or row.get("sample_started_mono")
        if isinstance(mono, int | float):
            if previous is not None:
                gaps.append(float(mono) - previous)
            previous = float(mono)
    return {
        "samples": len(rows),
        "max_gap_s": max(gaps) if gaps else None,
        "boot_id_changes": max(0, len(boot_ids) - 1),
        "registration_outage_samples": registration_outages,
        "data_outage_samples": data_outages,
        "address_outage_samples": address_outages,
        "route_outage_samples": route_outages,
    }


def count_false_runs(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is False)


def device_config_fingerprint(
    path_rows: dict[str, list[dict[str, Any]]],
    state: dict[str, Any],
) -> str:
    first_rows = {path: rows[0] for path, rows in path_rows.items() if rows}
    public_identity = {
        path: {
            "boot_id_hash": rutx12.pseudonym("boot", row.get("boot_id")),
            "operator": row.get("operator"),
            "rat": row.get("rat"),
            "primary_band": row.get("primary_band"),
            "interface": row.get("interface"),
            "device": row.get("device"),
        }
        for path, row in first_rows.items()
    }
    return rutx12.stable_hash(
        {"identity": public_identity, "qualified_port_pairs": state.get("qualified_port_pairs")}
    )


def raw_phase_durations(runtime: Path) -> dict[str, float | None]:
    events = rutx12.load_jsonl(runtime / "events.jsonl")
    by_type = {str(row.get("type")): row for row in events if isinstance(row, dict)}
    started = by_type.get("GATE_STARTED")
    load_started = by_type.get("LOAD_STARTED")
    load_stopped = by_type.get("LOAD_STOPPED")
    final = by_type.get("GATE_FINISHED") or by_type.get("FINAL_STATE_READY")
    return {
        "idle_s": elapsed_between(started, load_started),
        "loaded_s": elapsed_between(load_started, load_stopped),
        "post_s": elapsed_between(load_stopped, final),
    }


def elapsed_between(first: dict[str, Any] | None, second: dict[str, Any] | None) -> float | None:
    if not first or not second:
        return None
    a = first.get("mono")
    b = second.get("mono")
    if isinstance(a, int | float) and isinstance(b, int | float):
        return max(0.0, float(b) - float(a))
    return None


def write_public_manifest(runtime: Path, public: Path) -> None:
    manifest = read_json(runtime / "manifest.json", {})
    allowed = {
        "schema_version",
        "session_id",
        "route_id",
        "direction",
        "created_utc",
        "validation_only",
        "pinned_base_commit",
        "test_code_commit",
        "dirty_state_digest",
        "gate_fingerprint",
        "traffic",
    }
    write_json(public / "manifest.json", {key: manifest[key] for key in allowed if key in manifest})


def write_epoch_ledger(public: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "epoch_id",
        "path",
        "classification",
        "receiver_mbps",
        "loss_percent",
        "partial",
    ]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(str(row.get(col, "")) for col in columns))
    (public / "epoch-ledger.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(public: Path, summary: dict[str, Any]) -> None:
    attempted = summary["attempted_dual_epochs"]
    percent = summary["valid_dual_epochs"] / attempted * 100 if attempted else 0.0
    lines = [
        f"Result: {summary['classification']}",
        "Route: stationary-gate, direction stationary, moving-loaded duration 0 s",
        "Traffic: two simultaneous unshaped UDP uploads, 5,000,000 bit/s each, 1,200-byte payload",
        f"Receiver evidence: {summary['valid_dual_epochs']}/{attempted} ({percent:.1f}%)",
        f"GPS evidence: {summary['gps_valid_fixes']}/{summary['gps_samples']}",
        "",
        "Path A: delivery, RTT, outage and state continuity are derived only from raw ledgers.",
        "Path B: delivery, RTT, outage and state continuity are derived only from raw ledgers.",
        "Joint behavior: simultaneous usable windows are derived only from structurally "
        "valid receiver evidence.",
        f"Receiver quality: {summary['usable_receiver_epochs']} usable path epochs, "
        f"{summary['impaired_receiver_epochs']} impaired path epochs.",
        f"Port preflight: {len(summary.get('qualified_port_pairs') or [])} qualified pairs; "
        f"RB4011 egress isolation ok: {summary.get('egress_isolation_ok')}.",
        f"GPS limitation: {summary.get('gps_limitation') or 'none'}; "
        "GPS is not a stationary indoor gate blocker, but road start requires five "
        "outdoor minutes.",
        "",
        "Comparison status: NOT A METHOD-MATCHED LTAP COMPARISON.",
        "This is fixed-rate iPerf evidence, not GCC, encoded video, one-way video latency, "
        "or a production remote-driving qualification.",
        "",
        summary["ready_line"],
    ]
    (public / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_session(runtime: Path, public: Path) -> list[str]:
    problems = []
    for root in (runtime, public):
        problems.extend(rutx12.verify_checksums(root))
    summary = read_json(public / "summary.json", {})
    if summary.get("attempted_dual_epochs", 0) == 0 and summary.get("gate_passed"):
        problems.append("zero measured epochs cannot pass")
    if summary.get("attempted_dual_epochs", 0) == 0:
        problems.append("zero measured epochs cannot verify successfully")
    state = read_json(runtime / "STATE.json", {})
    if state.get("state") not in {"READY_FOR_ROAD", "BLOCKED_STATIONARY_GATE"}:
        problems.append("session state is not finalized")
    if state.get("state") == "READY_FOR_ROAD" and not summary.get("gate_passed"):
        problems.append("state/report consistency failure: READY_FOR_ROAD without gate_passed")
    if (
        summary.get("gate_passed")
        and summary.get("ready_line") != "READY FOR RUTX12 MOVING TEST: YES"
    ):
        problems.append("state/report consistency failure: gate_passed without READY YES")
    report = public / "report.md"
    if report.exists() and summary.get("ready_line") not in report.read_text(encoding="utf-8"):
        problems.append("state/report consistency failure: ready line missing from report")
    return problems


def install_signal_handlers(supervisor: Supervisor) -> None:
    def handle(_signum: int, _frame: Any) -> None:
        supervisor.event("SIGNAL_RECEIVED")
        supervisor.stop_event.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--name", default="car-stationary-gate")
    validate.add_argument("--idle-seconds", type=int, default=300)
    validate.add_argument("--load-seconds", type=int, default=300)
    validate.add_argument("--post-seconds", type=int, default=300)
    validate.set_defaults(func=validate_cmd)
    start = sub.add_parser("start")
    start.add_argument("--name", required=True)
    start.add_argument("--route-id", required=True)
    start.add_argument("--direction", required=True)
    start.add_argument("--gate-session-id", required=True)
    start.add_argument("--departure-authorized-by", required=True)
    start.set_defaults(func=start_cmd)
    sub.add_parser("status").set_defaults(func=status_cmd)
    sub.add_parser("load-start").set_defaults(func=load_start_cmd)
    mark = sub.add_parser("mark")
    mark.add_argument("label")
    mark.set_defaults(func=mark_cmd)
    load_stop = sub.add_parser("load-stop")
    load_stop.add_argument("--post-idle", type=int, default=300)
    load_stop.set_defaults(func=load_stop_cmd)
    sub.add_parser("stop").set_defaults(func=stop_cmd)
    supervise = sub.add_parser("supervise-road")
    supervise.add_argument("--session-id", required=True)
    supervise.set_defaults(func=supervise_road_cmd)
    verify = sub.add_parser("verify")
    verify.add_argument("--session-id", required=True)
    verify.set_defaults(func=verify_cmd)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--session-id", required=True)
    analyze.set_defaults(func=analyze_cmd)
    overnight = sub.add_parser("recompute-overnight")
    overnight.add_argument(
        "--run-dir",
        default=str(
            REPO / "runtime" / "rutx12-rb4011" / "20260905T195803Z-overnight-auto-dual5m-soak"
        ),
    )
    overnight.set_defaults(func=recompute_overnight_cmd)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
