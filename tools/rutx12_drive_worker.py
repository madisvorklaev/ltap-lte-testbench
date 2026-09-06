#!/usr/bin/env python3
"""RUTX12/RB4011 fixed-load moving-drive worker CLI.

The live road runner is deliberately gated: implementation/tests can run
offline, while `validate` records explicit blockers unless the physical setup,
RUT API access, GPS, and path isolation evidence are available.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ltap_testbench.drive_tests import rutx12  # noqa: E402

ROOT = REPO / "runtime" / "rutx12-drive"
PUBLIC_ROOT = REPO / "results-public" / "rutx12-drive"
ACTIVE = ROOT / "ACTIVE_SESSION.json"
PRIVATE_IDENTITY = ROOT / ".private-identity"
RB_HOST = "admin@192.168.88.1"
RUT_A = "root@192.168.11.1"
RUT_B = "root@192.168.12.1"
SSH_KEY = Path.home() / ".ssh" / "elmo_openclaw_ed25519"


def slug(value: str) -> str:
    import re

    out = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return out or "rutx12-drive"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def run(argv: list[str], timeout: float | None = None) -> dict[str, Any]:
    started_mono = time.monotonic()
    started_utc = rutx12.utc_now()
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return {
            "argv": redact_argv(argv),
            "started_utc": started_utc,
            "completed_utc": rutx12.utc_now(),
            "duration_s": time.monotonic() - started_mono,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": redact_argv(argv),
            "started_utc": started_utc,
            "completed_utc": rutx12.utc_now(),
            "duration_s": time.monotonic() - started_mono,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timeout": True,
        }


def redact_argv(argv: list[str]) -> list[str]:
    return ["<ssh-key>" if str(SSH_KEY) == item else item for item in argv]


def ssh_base(host: str, timeout: int = 5) -> list[str]:
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
        f"ConnectTimeout={timeout}",
        host,
    ]


def create_manifest(name: str, route_id: str, direction: str, validation: bool) -> dict[str, Any]:
    commit = run(["git", "-C", str(REPO), "rev-parse", "HEAD"], timeout=5)
    dirty = run(["git", "-C", str(REPO), "status", "--short"], timeout=5)
    session_id = f"rutx12-drive-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{slug(name)}"
    return {
        "schema_version": rutx12.SCHEMA_VERSION,
        "session_id": session_id,
        "name": name,
        "route_id": route_id,
        "direction": direction,
        "validation_only": validation,
        "created_utc": rutx12.utc_now(),
        "pinned_base_commit": rutx12.PINNED_BASE_COMMIT,
        "test_code_commit": (commit.get("stdout") or "").strip(),
        "dirty_state_digest": rutx12.stable_hash(dirty.get("stdout", "")),
        "topology": "RB4011 plus two RUTX12, one active modem per RUT",
        "traffic": {
            "server_ipv4": rutx12.SERVER_IPV4,
            "rate_bps_per_path": rutx12.REQUIRED_RATE_BPS,
            "payload_bytes": rutx12.REQUIRED_PAYLOAD_BYTES,
            "udp": True,
            "ipv4": True,
            "parallel_streams_per_path": 1,
            "epoch_seconds": 10,
            "sources": {"path-a": rutx12.SOURCE_A, "path-b": rutx12.SOURCE_B},
            "port_pairs": rutx12.PORT_PAIRS,
        },
        "private_identity_map": str(PRIVATE_IDENTITY),
        "gps_policy": "precise GPS remains private unless explicitly approved",
    }


def session_paths(session_id: str) -> tuple[Path, Path]:
    return ROOT / session_id, PUBLIC_ROOT / session_id


def active_session() -> dict[str, Any]:
    return read_json(ACTIVE, {})


def require_active() -> tuple[dict[str, Any], Path, Path]:
    state = active_session()
    session_id = state.get("session_id")
    if not session_id:
        raise SystemExit("No active RUTX12 drive session.")
    runtime, public = session_paths(session_id)
    return state, runtime, public


def write_state(runtime: Path, state: dict[str, Any]) -> None:
    state["updated_utc"] = rutx12.utc_now()
    rutx12.atomic_json(runtime / "STATE.json", state)
    rutx12.atomic_json(
        runtime / "HEARTBEAT.json",
        {
            "session_id": state["session_id"],
            "state": state["state"],
            "updated_utc": state["updated_utc"],
        },
    )
    terminal_states = {
        "COMPLETE",
        "ABORTED",
        "INVALID",
        "BLOCKED_STATIONARY_GATE",
    }
    if state["state"] not in terminal_states:
        rutx12.atomic_json(ACTIVE, state)
    elif ACTIVE.exists():
        active = active_session()
        if active.get("session_id") == state.get("session_id"):
            ACTIVE.unlink()


def init_session(args: argparse.Namespace, validation: bool) -> tuple[dict[str, Any], Path, Path]:
    if ACTIVE.exists():
        active = active_session()
        pid = active.get("worker_pid")
        if isinstance(pid, int) and Path(f"/proc/{pid}").exists():
            session_id = active.get("session_id")
            raise SystemExit(f"Active RUTX12 drive session already running: {session_id}")
    manifest = create_manifest(
        args.name,
        getattr(args, "route_id", "stationary-gate"),
        getattr(args, "direction", "stationary"),
        validation,
    )
    runtime, public = session_paths(manifest["session_id"])
    for subdir in (
        runtime / "baseline",
        runtime / "raw",
        runtime / "gps",
        runtime / "rut-a",
        runtime / "rut-b",
        runtime / "rb4011",
        runtime / "probes",
        runtime / "traffic",
        runtime / "logs",
        runtime / "capture",
        runtime / "derived",
        public,
    ):
        subdir.mkdir(parents=True, exist_ok=True)
    rutx12.atomic_json(runtime / "manifest.json", manifest)
    state = {
        "session_id": manifest["session_id"],
        "state": "PRESTART",
        "created_utc": manifest["created_utc"],
        "runtime_dir": str(runtime),
        "public_dir": str(public),
        "validation_only": validation,
        "phase": "PRESTART",
    }
    write_state(runtime, state)
    rutx12.append_jsonl(
        runtime / "events.jsonl",
        {
            "utc": rutx12.utc_now(),
            "type": "SESSION_CREATED",
            "validation_only": validation,
        },
    )
    return state, runtime, public


def validate_cmd(args: argparse.Namespace) -> int:
    state, runtime, public = init_session(args, validation=True)
    blockers = live_gate_blockers(runtime)
    if blockers:
        state["state"] = "BLOCKED_STATIONARY_GATE"
        state["blockers"] = blockers
        write_state(runtime, state)
        write_checkpoint_artifacts(runtime, public, blockers)
        print(f"READY FOR RUTX12 MOVING TEST: NO - {blockers[0]}")
        return 2
    state["state"] = "READY_STATIONARY_GATE"
    state["phase"] = "POST_IDLE"
    write_state(runtime, state)
    write_checkpoint_artifacts(runtime, public, [])
    print("READY FOR RUTX12 MOVING TEST: YES")
    return 0


def write_checkpoint_artifacts(runtime: Path, public: Path, blockers: list[str]) -> None:
    manifest = read_json(runtime / "manifest.json", {})
    events = rutx12.load_jsonl(runtime / "events.jsonl")
    result = {
        "session_id": runtime.name,
        "classification": "RUTX12_MOVING_TEST_INVALID" if blockers else "RUTX12_MOVING_TEST_VALID",
        "blockers": blockers,
        "valid_receiver_epochs": 0,
        "invalid_receiver_epochs": 0,
        "unknown_receiver_epochs": 0,
        "fixed_rate_iperf_not_gcc_video": True,
    }
    public.mkdir(parents=True, exist_ok=True)
    rutx12.atomic_json(runtime / "derived" / "joint-metrics.json", result)
    rutx12.atomic_json(public / "joint-metrics.json", result)
    (public / "events.json").write_text(
        json.dumps(events, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (public / "epoch-ledger.csv").write_text(
        "epoch_id,path,classification,receiver_mbps,loss_percent\n",
        encoding="utf-8",
    )
    (public / "manifest.json").write_text(
        json.dumps(public_manifest(manifest), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    write_public_gate_report(public, runtime.name, blockers)
    rutx12.write_checksums(runtime)
    rutx12.write_checksums(public)


def live_gate_blockers(runtime: Path) -> list[str]:
    blockers: list[str] = []
    if not SSH_KEY.exists():
        blockers.append("SSH_KEY_MISSING")
    host_route = run(
        ["ip", "route", "get", rutx12.SERVER_IPV4, "from", rutx12.SOURCE_A],
        timeout=5,
    )
    host_route_b = run(
        ["ip", "route", "get", rutx12.SERVER_IPV4, "from", rutx12.SOURCE_B],
        timeout=5,
    )
    rutx12.atomic_json(runtime / "baseline" / "host-route-a.json", host_route)
    rutx12.atomic_json(runtime / "baseline" / "host-route-b.json", host_route_b)
    if host_route["returncode"] != 0 or rutx12.SOURCE_A not in host_route.get("stdout", ""):
        blockers.append("PATH_A_SOURCE_ROUTE_NOT_PROVEN")
    if host_route_b["returncode"] != 0 or rutx12.SOURCE_B not in host_route_b.get("stdout", ""):
        blockers.append("PATH_B_SOURCE_ROUTE_NOT_PROVEN")
    rb_command = (
        "/ip route print detail; /routing rule print detail; /queue tree print detail; "
        '/ip firewall mangle print stats detail where comment~"ELMO|RUTX"'
    )
    rb = run([*ssh_base(RB_HOST), rb_command], timeout=12)
    rutx12.atomic_json(runtime / "rb4011" / "baseline.json", rb)
    if rb["returncode"] != 0:
        blockers.append("RB4011_SSH_NOT_AVAILABLE")
    for label, host in (("rut-a", RUT_A), ("rut-b", RUT_B)):
        rut_command = "ubus call system board; ubus call system info; logread -l 20"
        status = run([*ssh_base(host), rut_command], timeout=12)
        rutx12.atomic_json(runtime / label / "baseline.json", status)
        if status["returncode"] != 0:
            blockers.append(f"{label.upper()}_SSH_NOT_AVAILABLE")
    # The detailed collector/GPS/API proof is a hard gate; the initial command
    # records what is reachable and then stops until equipment is actually ready.
    blockers.append("FULL_15_MIN_STATIONARY_GATE_NOT_YET_RUN")
    return blockers


def write_public_gate_report(public: Path, session_id: str, blockers: list[str]) -> None:
    public.mkdir(parents=True, exist_ok=True)
    status = "NO - " + blockers[0] if blockers else "YES"
    (public / "report.md").write_text(
        "Result: RUTX12_MOVING_TEST_INVALID\n"
        "Route: stationary-gate, direction stationary, moving-loaded duration 0 s\n"
        "Traffic: two simultaneous unshaped UDP uploads, 5,000,000 bit/s each, 1,200-byte payload\n"
        "Receiver evidence: 0/0 (0%)\n"
        "GPS evidence: 0/0 (0%)\n\n"
        "Path A: stationary live gate did not complete, so no road delivery verdict exists.\n"
        "Path B: stationary live gate did not complete, so no road delivery verdict exists.\n"
        "Joint behavior: no moving test has been authorized or run.\n\n"
        "Comparison status: NOT A METHOD-MATCHED LTAP COMPARISON.\n"
        "This run characterizes the RB4011 plus two-RUTX12 fixed-load upload proxy while moving. "
        "It does not test GCC, encoded video, one-way or capture-to-display latency, "
        "or production safety. "
        "A fresh method-matched LtAP road control would be required to conclude that one "
        "hardware topology performs better; "
        "the known LtAP LTE7 failure is a separate operational finding.\n\n"
        f"Stationary gate session: `{session_id}`\n\n"
        f"READY FOR RUTX12 MOVING TEST: {status}\n",
        encoding="utf-8",
    )


def start_cmd(args: argparse.Namespace) -> int:
    state, runtime, _public = init_session(args, validation=False)
    state["state"] = "PRE_IDLE"
    state["route_id"] = args.route_id
    state["direction"] = args.direction
    write_state(runtime, state)
    print(
        "RUTX12 drive session prepared.\n"
        f"Session: {state['session_id']}\n"
        "State: PRE_IDLE\n"
        "Load: stopped"
    )
    return 0


def status_cmd(_args: argparse.Namespace) -> int:
    state, runtime, _public = require_active()
    current = read_json(runtime / "STATE.json", state)
    print(json.dumps(current, indent=2, sort_keys=True))
    return 0


def load_start_cmd(_args: argparse.Namespace) -> int:
    state, runtime, _public = require_active()
    if state.get("state") not in {"PRE_IDLE", "LOADED_PARKED"}:
        raise SystemExit(f"Cannot start load from state {state.get('state')}")
    state["state"] = "LOADED_PARKED"
    state["load_started_utc"] = rutx12.utc_now()
    rutx12.append_jsonl(
        runtime / "events.jsonl",
        {"utc": state["load_started_utc"], "type": "LOAD_STARTED"},
    )
    write_state(runtime, state)
    print("Load state recorded: LOADED_PARKED")
    return 0


def mark_cmd(args: argparse.Namespace) -> int:
    state, runtime, _public = require_active()
    rutx12.append_jsonl(
        runtime / "events.jsonl",
        {"utc": rutx12.utc_now(), "type": "HUMAN_MARK", "label": args.label},
    )
    if args.label.startswith("DEPART_"):
        state["state"] = "MOVING_LOADED"
    elif args.label.startswith("ARRIVE_"):
        state["state"] = "ARRIVED_LOADED"
    write_state(runtime, state)
    print(f"Marked: {args.label}")
    return 0


def load_stop_cmd(args: argparse.Namespace) -> int:
    state, runtime, _public = require_active()
    state["state"] = "POST_IDLE"
    state["load_stopped_utc"] = rutx12.utc_now()
    state["post_idle_s"] = args.post_idle
    rutx12.append_jsonl(
        runtime / "events.jsonl",
        {
            "utc": state["load_stopped_utc"],
            "type": "LOAD_STOPPED",
            "post_idle_s": args.post_idle,
        },
    )
    write_state(runtime, state)
    print("Load state recorded: POST_IDLE")
    return 0


def stop_cmd(_args: argparse.Namespace) -> int:
    state, runtime, public = require_active()
    state["state"] = "ANALYZING"
    write_state(runtime, state)
    analyze_session(runtime, public)
    rutx12.write_checksums(runtime)
    state["state"] = "COMPLETE"
    write_state(runtime, state)
    if ACTIVE.exists():
        ACTIVE.unlink()
    print(f"Stopped and analyzed: {state['session_id']}")
    return 0


def analyze_cmd(args: argparse.Namespace) -> int:
    runtime, public = session_paths(args.session_id)
    result = analyze_session(runtime, public)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def verify_cmd(args: argparse.Namespace) -> int:
    runtime, public = session_paths(args.session_id)
    summary = analyze_session(runtime, public)
    problems = []
    if not (runtime / "manifest.json").exists():
        problems.append("manifest missing")
    if summary.get("classification") == "RUTX12_MOVING_TEST_INVALID":
        problems.append("session invalid")
    rc = 1 if problems else 0
    print(
        json.dumps(
            {
                "session_id": args.session_id,
                "returncode": rc,
                "problems": problems,
                "summary": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return rc


def recompute_overnight_cmd(args: argparse.Namespace) -> int:
    summary = rutx12.recompute_overnight_soak(Path(args.run_dir))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def analyze_session(runtime: Path, public: Path) -> dict[str, Any]:
    public.mkdir(parents=True, exist_ok=True)
    events = rutx12.load_jsonl(runtime / "events.jsonl")
    manifest = read_json(runtime / "manifest.json", {})
    classification = "RUTX12_MOVING_TEST_INVALID"
    if any(e.get("type") == "LOAD_STARTED" for e in events) and any(
        e.get("type") == "LOAD_STOPPED" for e in events
    ):
        classification = "RUTX12_MOVING_TEST_VALID_WITH_LIMITATIONS"
    result = {
        "session_id": runtime.name,
        "classification": classification,
        "manifest": bool(manifest),
        "events": len(events),
        "valid_receiver_epochs": 0,
        "invalid_receiver_epochs": 0,
        "unknown_receiver_epochs": 0,
        "fixed_rate_iperf_not_gcc_video": True,
    }
    rutx12.atomic_json(runtime / "derived" / "joint-metrics.json", result)
    rutx12.atomic_json(public / "joint-metrics.json", result)
    (public / "events.json").write_text(
        json.dumps(events, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (public / "epoch-ledger.csv").write_text(
        "epoch_id,path,classification,receiver_mbps,loss_percent\n",
        encoding="utf-8",
    )
    (public / "manifest.json").write_text(
        json.dumps(public_manifest(manifest), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    report_blockers = (
        ["NO_MEASURED_ROAD_RUN"]
        if classification == "RUTX12_MOVING_TEST_INVALID"
        else []
    )
    write_public_gate_report(public, runtime.name, report_blockers)
    return result


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "session_id",
        "name",
        "route_id",
        "direction",
        "validation_only",
        "created_utc",
        "pinned_base_commit",
        "test_code_commit",
        "dirty_state_digest",
        "topology",
        "traffic",
        "gps_policy",
    }
    return {k: v for k, v in manifest.items() if k in allowed}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--name", default="car-stationary-gate")
    validate.set_defaults(func=validate_cmd)

    start = sub.add_parser("start")
    start.add_argument("--name", required=True)
    start.add_argument("--route-id", required=True)
    start.add_argument("--direction", required=True)
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

    verify = sub.add_parser("verify")
    verify.add_argument("--session-id", required=True)
    verify.set_defaults(func=verify_cmd)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--session-id", required=True)
    analyze.set_defaults(func=analyze_cmd)

    overnight = sub.add_parser("recompute-overnight")
    default_overnight = (
        REPO
        / "runtime"
        / "rutx12-rb4011"
        / "20260905T195803Z-overnight-auto-dual5m-soak"
    )
    overnight.add_argument("--run-dir", default=str(default_overnight))
    overnight.set_defaults(func=recompute_overnight_cmd)

    args = parser.parse_args()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
