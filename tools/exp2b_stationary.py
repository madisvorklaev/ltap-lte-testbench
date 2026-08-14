#!/usr/bin/env python3
"""Stationary ELMO Experiment 2b PFIFO/CAKE queue-control runner.

This wrapper deliberately performs only read-only RouterOS operations. RSC
imports and all router configuration changes remain manual operator actions.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import re
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
CAMPAIGN = REPO / "references/public-iperf-kit/campaign.json"
CAMPAIGN_LTE1 = REPO / "references/public-iperf-kit/campaign-dual-lte1.json"
CAMPAIGN_LTE2 = REPO / "references/public-iperf-kit/campaign-dual-lte2.json"
PUBLIC = REPO / "results-public/exp2b-stationary-20260814"
RUNTIME = REPO / "runtime/exp2b-stationary-20260814"

SENSITIVE_RE = re.compile(r"\b(imei|imsi|iccid|uicc|subscriber-number|serial-number|software-id)\b", re.I)


def load_collector() -> Any:
    spec = importlib.util.spec_from_file_location("ltap_public_test", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import collector from {COLLECTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_collector()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sanitize_text(value: str) -> str:
    lines = []
    for line in value.splitlines():
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if SENSITIVE_RE.search(key) or SENSITIVE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: sanitize_obj(v)
            for k, v in obj.items()
            if not SENSITIVE_RE.search(k)
        }
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, str):
        return sanitize_text(obj)
    return obj


def sanitize_file(path: Path) -> None:
    if path.suffix == ".json":
        try:
            save_json(path, sanitize_obj(load_json(path)))
            return
        except Exception:
            pass
    if path.suffix == ".jsonl":
        out = []
        changed = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                clean = sanitize_obj(row)
                out.append(json.dumps(clean, ensure_ascii=False))
                changed = changed or clean != row
            except json.JSONDecodeError:
                clean_line = sanitize_text(line)
                out.append(clean_line)
                changed = changed or clean_line != line
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return
    if path.suffix in {".txt", ".log", ".stderr", ".stdout"}:
        value = path.read_text(encoding="utf-8", errors="replace")
        clean = sanitize_text(value)
        if clean != value:
            path.write_text(clean, encoding="utf-8")


def sanitize_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_file():
            sanitize_file(child)


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, timeout=timeout)


def router_call(router: Any, command: str, timeout: float = 10) -> dict[str, Any]:
    try:
        cp = router.call(command, timeout=timeout)
        return {
            "command": command,
            "rc": cp.returncode,
            "stdout": sanitize_text(cp.stdout),
            "stderr": sanitize_text(cp.stderr),
        }
    except Exception as exc:
        return {"command": command, "error": repr(exc)}


def verify_condition(router: Any, condition: str) -> dict[str, Any]:
    if condition == "B":
        queue_type = '/queue/type/print detail where name="elmo-exp2b-pfifo"'
    elif condition == "C":
        queue_type = '/queue/type/print detail where name="elmo-exp2b-cake"'
    else:
        queue_type = '/queue/tree/print stats detail where name~"ELMO-EXP2B"'
    commands = [
        queue_type,
        '/queue/tree/print detail where name="ELMO-EXP2B-LTE1"',
        '/queue/tree/print detail where name="ELMO-EXP2B-LTE2"',
        '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE1"',
        '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE2"',
        '/ip/firewall/mangle/print stats detail where comment~"ELMO EXP2B:"',
        '/system/resource/print',
        '/interface/lte/monitor lte1 once',
        '/interface/lte/monitor lte2 once',
        '/interface/print stats-detail where name="lte1"',
        '/interface/print stats-detail where name="lte2"',
    ]
    out = {"condition": condition, "timestamp_utc": utc_now(), "commands": []}
    for command in commands:
        out["commands"].append(router_call(router, command))
    joined = "\n".join(x.get("stdout", "") for x in out["commands"])
    checks = {
        "lte1_tree_present": "ELMO-EXP2B-LTE1" in joined,
        "lte2_tree_present": "ELMO-EXP2B-LTE2" in joined,
        "max_limit_5m_present": "max-limit=5M" in joined or "max-limit=5 000 000" in joined,
        "mangle_marks_present": "ELMO EXP2B:" in joined,
        "pfifo_type_present": condition != "B" or "elmo-exp2b-pfifo" in joined,
        "cake_type_present": condition != "C" or "elmo-exp2b-cake" in joined,
        "cake_bandwidth_disabled": condition != "C" or "cake-bandwidth=0" in joined,
        "cake_flowblind": condition != "C" or "cake-flowmode=flowblind" in joined,
    }
    out["checks"] = checks
    out["ok"] = all(checks.values()) if condition in {"B", "C"} else True
    save_json(PUBLIC / f"verify_condition_{condition}.json", sanitize_obj(out))
    return out


def queue_sampler(router: Any, run_id: str, stop: threading.Event) -> None:
    path = PUBLIC / "queue_telemetry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    commands = {
        "queue_lte1": '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE1"',
        "queue_lte2": '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE2"',
        "resource": "/system/resource/print",
    }
    with path.open("a", encoding="utf-8") as f:
        while not stop.is_set():
            row = {"timestamp_utc": utc_now(), "run_id": run_id}
            for name, command in commands.items():
                row[name] = router_call(router, command, timeout=8)
            f.write(json.dumps(sanitize_obj(row), ensure_ascii=False) + "\n")
            f.flush()
            stop.wait(1.0)


def collector_cmd(path_name: str, tag: str, duration: int, bitrate: str, campaign: Path) -> list[str]:
    return [
        sys.executable,
        str(COLLECTOR_PATH),
        "--config",
        str(CONFIG),
        "run",
        "--path",
        path_name,
        "--campaign",
        str(campaign),
        "--protocol",
        "udp",
        "--bitrate",
        bitrate,
        "--packet-length",
        "1200",
        "--duration",
        str(duration),
        "--warmup",
        "5",
        "--cooldown",
        "10",
        "--telemetry-interval",
        "1",
        "--ping-interval",
        "0.2",
        "--allow-concurrent-other-lte",
        "--tag",
        tag,
        "--output",
        str(PUBLIC / "runs"),
    ]


def run_processes(run_id: str, commands: list[list[str]], router: Any) -> dict[str, Any]:
    stop = threading.Event()
    sampler = threading.Thread(target=queue_sampler, args=(router, run_id, stop), daemon=True)
    sampler.start()
    started = utc_now()
    procs = []
    logs = RUNTIME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        for idx, cmd in enumerate(commands, 1):
            stdout = (logs / f"{run_id}_{idx}.stdout").open("w", encoding="utf-8")
            stderr = (logs / f"{run_id}_{idx}.stderr").open("w", encoding="utf-8")
            procs.append((subprocess.Popen(cmd, cwd=REPO, stdout=stdout, stderr=stderr, text=True), stdout, stderr, cmd))
        exit_codes = []
        for proc, stdout, stderr, _cmd in procs:
            exit_codes.append(proc.wait())
            stdout.close()
            stderr.close()
    finally:
        stop.set()
        sampler.join(timeout=10)
        for proc, stdout, stderr, _cmd in procs:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
            if not stdout.closed:
                stdout.close()
            if not stderr.closed:
                stderr.close()
    result = {
        "run_id": run_id,
        "started_utc": started,
        "finished_utc": utc_now(),
        "commands": [" ".join(cmd) for _proc, _out, _err, cmd in procs],
        "exit_codes": exit_codes,
        "ok": all(code == 0 for code in exit_codes),
    }
    sanitize_tree(PUBLIC / "runs")
    sanitize_tree(RUNTIME / "logs")
    save_json(PUBLIC / "run_status" / f"{run_id}.json", result)
    return result


def sequence(condition: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path_name in ("lte1", "lte2"):
        for repeat in range(1, 4):
            out.append({"id": f"{condition}_{path_name}_6M_r{repeat}", "paths": [path_name], "duration": 120, "bitrate": "6M"})
    for repeat in range(1, 4):
        out.append({"id": f"{condition}_dual_6M_r{repeat}", "paths": ["lte1", "lte2"], "duration": 300, "bitrate": "6M"})
    for repeat in range(1, 3):
        out.append({"id": f"{condition}_dual_5M_control_r{repeat}", "paths": ["lte1", "lte2"], "duration": 300, "bitrate": "5M"})
    return out


def write_manifest(condition: str) -> None:
    campaign = load_json(CAMPAIGN)
    manifest = {
        "experiment": "ELMO Experiment 2b stationary LTE queue-control test",
        "condition": condition,
        "git_commit": run(["git", "rev-parse", "HEAD"], timeout=5).stdout.strip(),
        "collector_version": collector.VERSION,
        "created_utc": utc_now(),
        "server_hostname": campaign.get("server_hostname"),
        "server_ipv4": campaign.get("server_ipv4"),
        "ports": campaign.get("ports"),
        "fixed_cap": "5M for B/C imported manually by operator",
        "test_rates": ["6M per path", "5M dual lower-load control"],
        "durations": {"single_path_seconds": 120, "dual_seconds": 300},
        "router_changes_by_openclaw": "none",
    }
    save_json(PUBLIC / "experiment_manifest.json", manifest)


def collect_summaries() -> list[dict[str, Any]]:
    rows = []
    for summary_path in sorted((PUBLIC / "runs").glob("*/summary.json")):
        try:
            summary = load_json(summary_path)
        except Exception:
            continue
        test = summary.get("test", {})
        rows.append({
            "tag": test.get("tag"),
            "path": test.get("path"),
            "duration_s": test.get("duration_s"),
            "target_bitrate": test.get("target_bitrate"),
            "actual_mbps": (summary.get("iperf") or {}).get("mbps"),
            "udp_loss_percent": (summary.get("iperf") or {}).get("lost_percent"),
            "udp_jitter_ms": (summary.get("iperf") or {}).get("jitter_ms"),
            "ping_avg_ms": (summary.get("ping") or {}).get("avg_ms"),
            "ping_p95_ms": (summary.get("ping") or {}).get("p95_ms"),
            "ping_max_ms": (summary.get("ping") or {}).get("max_ms"),
            "ping_loss_percent": (summary.get("ping") or {}).get("loss_percent"),
            "primary_bands_seen": "|".join((summary.get("radio_target") or {}).get("primary_bands_seen") or []),
            "ca_bands_seen": "|".join((summary.get("radio_target") or {}).get("ca_bands_seen") or []),
            "cell_changes": (summary.get("radio_target") or {}).get("cell_changes"),
            "path_verification": summary.get("path_verification"),
            "test_dir": str(summary_path.parent),
        })
    return rows


def write_comparison(condition: str, statuses: list[dict[str, Any]]) -> None:
    rows = collect_summaries()
    fields = [
        "tag", "path", "duration_s", "target_bitrate", "actual_mbps", "udp_loss_percent",
        "udp_jitter_ms", "ping_avg_ms", "ping_p95_ms", "ping_max_ms", "ping_loss_percent",
        "primary_bands_seen", "ca_bands_seen", "cell_changes", "path_verification", "test_dir",
    ]
    with (PUBLIC / "comparison_runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "condition": condition,
        "updated_utc": utc_now(),
        "run_statuses": statuses,
        "runs": rows,
        "labels": {
            "network_queue_latency_evidence": "pending final A/B/C comparison",
            "actual_video_frame_age_evidence": "not collected by this stationary iPerf/ping campaign",
        },
    }
    save_json(PUBLIC / "comparison_summary.json", summary)
    lines = [
        "# ELMO Experiment 2b Stationary Report",
        "",
        f"Updated: {summary['updated_utc']}",
        f"Current condition: {condition}",
        "",
        "OpenClaw made no RouterOS configuration changes. RSC imports are manual boundaries.",
        "",
        "## Current Status",
        "",
    ]
    for status in statuses:
        state = "OK" if status.get("ok") else "FAILED"
        lines.append(f"- {status['run_id']}: {state} exit_codes={status.get('exit_codes')}")
    lines.extend([
        "",
        "## Evidence Boundary",
        "",
        "- Network queue/latency evidence: collected from iPerf receiver metrics, path-bound ping, LTE telemetry, RouterOS resource state, and Exp2b queue telemetry.",
        "- Actual video frame-age evidence: not collected in this stationary iPerf campaign.",
        "",
        "Do not treat ping alone as proof that displayed production video latency is fixed.",
    ])
    (PUBLIC / "EXP2B_STATIONARY_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=["B", "C"], required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--sanitize-only", action="store_true")
    args = parser.parse_args()

    PUBLIC.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if args.sanitize_only:
        sanitize_tree(PUBLIC)
        sanitize_tree(RUNTIME / "logs")
        return 0
    write_manifest(args.condition)
    cfg = load_json(CONFIG)
    router = collector.RouterSSH(cfg["router"])
    try:
        verification = verify_condition(router, args.condition)
        print(json.dumps(verification["checks"], indent=2))
        if not verification.get("ok"):
            print(f"Condition {args.condition} verification failed. Stopping.", file=sys.stderr)
            return 2
        if args.verify_only:
            return 0

        statuses = []
        for item in sequence(args.condition):
            run_id = item["id"]
            status_path = PUBLIC / "run_status" / f"{run_id}.json"
            if status_path.exists() and load_json(status_path).get("ok"):
                statuses.append(load_json(status_path))
                continue
            print(f"[{utc_now()}] starting {run_id}", flush=True)
            commands = []
            for path_name in item["paths"]:
                campaign = CAMPAIGN_LTE1 if path_name == "lte1" and len(item["paths"]) > 1 else CAMPAIGN_LTE2 if path_name == "lte2" and len(item["paths"]) > 1 else CAMPAIGN
                commands.append(collector_cmd(path_name, run_id, item["duration"], item["bitrate"], campaign))
            status = run_processes(run_id, commands, router)
            statuses.append(status)
            write_comparison(args.condition, statuses)
            if not status["ok"]:
                print(f"{run_id} failed; preserving artifacts and stopping.", file=sys.stderr)
                return 3
            time.sleep(35)
        write_comparison(args.condition, statuses)
    finally:
        router.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
