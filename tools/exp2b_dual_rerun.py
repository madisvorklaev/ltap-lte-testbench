#!/usr/bin/env python3
"""Repair runner for Experiment 2b simultaneous PFIFO/CAKE dual-load tests."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import math
import os
import re
import shlex
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
PUBLIC = REPO / "results-public/exp2b-dual-rerun-20260814"
RUNTIME = REPO / "runtime/exp2b-dual-rerun-20260814"

CONDITIONS = {
    "B": {
        "label": "PFIFO",
        "rsc": "ELMO-experiment-2b-rate-control-pfifo-v2.rsc",
        "queue_type": "elmo-exp2b-pfifo",
        "queue_kind": "pfifo",
        "required": ["pfifo-limit=50"],
    },
    "C": {
        "label": "CAKE",
        "rsc": "ELMO-experiment-2b-lte-aqm-cake-v2.rsc",
        "queue_type": "elmo-exp2b-cake",
        "queue_kind": "cake",
        "required": ["cake-bandwidth=0", "cake-diffserv=besteffort", "cake-flowmode=flowblind"],
    },
}

SENSITIVE_RE = re.compile(r"\b(imei|imsi|iccid|uicc|subscriber-number|serial-number|software-id|password|secret|token)\b", re.I)


def load_collector() -> Any:
    spec = importlib.util.spec_from_file_location("ltap_public_test", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import collector from {COLLECTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_collector()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def local_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run(cmd: list[str], timeout: float | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd or REPO, text=True, capture_output=True, timeout=timeout)


def sanitize_text(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if SENSITIVE_RE.search(key) or SENSITIVE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items() if not SENSITIVE_RE.search(k)}
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
        rows: list[str] = []
        changed = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                raw = json.loads(line)
                clean = sanitize_obj(raw)
                rows.append(json.dumps(clean, ensure_ascii=True))
                changed = changed or clean != raw
            except json.JSONDecodeError:
                clean_line = sanitize_text(line)
                rows.append(clean_line)
                changed = changed or clean_line != line
        if changed:
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return
    if path.suffix in {".txt", ".log", ".stderr", ".stdout", ".md", ".csv"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        clean = sanitize_text(raw)
        if clean != raw:
            path.write_text(clean, encoding="utf-8")


def sanitize_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_file():
            sanitize_file(child)


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


def ssh_base(cfg: dict[str, Any]) -> list[str]:
    router = cfg["router"]
    cmd = [
        "ssh",
        "-p",
        str(router.get("port", 22)),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
    ]
    key = router.get("ssh_key")
    if key:
        cmd += ["-i", os.path.expanduser(key)]
    cmd.append(f"{router.get('user', 'admin')}@{router['host']}")
    return cmd


def scp_base(cfg: dict[str, Any]) -> list[str]:
    router = cfg["router"]
    cmd = [
        "scp",
        "-P",
        str(router.get("port", 22)),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
    ]
    key = router.get("ssh_key")
    if key:
        cmd += ["-i", os.path.expanduser(key)]
    return cmd


def remote(cfg: dict[str, Any], filename: str) -> str:
    router = cfg["router"]
    return f"{router.get('user', 'admin')}@{router['host']}:{filename}"


def import_condition(cfg: dict[str, Any], condition: str) -> dict[str, Any]:
    spec = CONDITIONS[condition]
    imports_dir = RUNTIME / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    original = imports_dir / spec["rsc"]
    wrapped_name = f"OPENCLAW-{condition}-wrapped-{int(time.time())}.rsc"
    wrapped = imports_dir / wrapped_name

    fetch = run(scp_base(cfg) + [remote(cfg, spec["rsc"]), str(original)], timeout=15)
    if fetch.returncode != 0:
        raise RuntimeError(f"Could not fetch {spec['rsc']}: {fetch.stderr.strip()}")
    with original.open("r", encoding="utf-8", errors="replace") as src, wrapped.open("w", encoding="utf-8") as dst:
        dst.write(":do {\n")
        for line in src:
            dst.write("    " + line)
        dst.write("\n}\n")
    upload = run(scp_base(cfg) + [str(wrapped), remote(cfg, wrapped_name)], timeout=15)
    if upload.returncode != 0:
        raise RuntimeError(f"Could not upload wrapped {condition} RSC: {upload.stderr.strip()}")

    dry_cmd = f"/import file-name={wrapped_name} verbose=yes dry-run"
    imp_cmd = f"/import file-name={wrapped_name} verbose=yes"
    dry = run(ssh_base(cfg) + [dry_cmd], timeout=20)
    apply = run(ssh_base(cfg) + [imp_cmd], timeout=30) if dry.returncode == 0 else subprocess.CompletedProcess([], 99, "", "dry-run failed")
    result = {
        "condition": condition,
        "timestamp_utc": utc_now(),
        "source_rsc": spec["rsc"],
        "wrapped_rsc": wrapped_name,
        "dry_run": {"rc": dry.returncode, "stdout": sanitize_text(dry.stdout), "stderr": sanitize_text(dry.stderr)},
        "import": {"rc": apply.returncode, "stdout": sanitize_text(apply.stdout), "stderr": sanitize_text(apply.stderr)},
    }
    save_json(PUBLIC / f"import_condition_{condition}.json", result)
    if dry.returncode != 0 or apply.returncode != 0:
        raise RuntimeError(f"Condition {condition} import failed")
    return result


def parse_counter_stdout(stdout: str) -> dict[str, int]:
    compact = " ".join(stdout.splitlines())
    out: dict[str, int] = {}
    for key in ("bytes", "packets", "dropped", "queued-bytes", "queued-packets"):
        matches = re.findall(rf"(?:^|\s){re.escape(key)}=([0-9 ]+)", compact)
        if matches:
            try:
                out[key] = int(matches[-1].replace(" ", ""))
            except ValueError:
                pass
    return out


def ping_smoke(cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"timestamp_utc": utc_now(), "paths": {}}
    for path_name, path_cfg in cfg["paths"].items():
        cp = run(["ping", "-n", "-I", path_cfg["source_ip"], "-c", "3", "-W", "2", "1.1.1.1"], timeout=10)
        out["paths"][path_name] = {
            "source_ip": path_cfg["source_ip"],
            "rc": cp.returncode,
            "stdout": sanitize_text(cp.stdout),
            "stderr": sanitize_text(cp.stderr),
        }
    return out


def verify_condition(cfg: dict[str, Any], condition: str, suffix: str) -> dict[str, Any]:
    spec = CONDITIONS[condition]
    router = collector.RouterSSH(cfg["router"])
    commands = [
        f'/queue/type/print detail where name="{spec["queue_type"]}"',
        '/queue/tree/print detail where name="ELMO-EXP2B-LTE1"',
        '/queue/tree/print detail where name="ELMO-EXP2B-LTE2"',
        '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE1"',
        '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE2"',
        '/ip/firewall/mangle/print stats detail where comment~"ELMO EXP2B:"',
        '/ip/firewall/mangle/print detail where comment~"ELMO EXP2B|ELMO TEST: source via"',
        '/ip/firewall/filter/print detail where action=fasttrack-connection disabled=no',
        '/system/identity/print',
        '/system/resource/print',
        '/system/routerboard/print',
        '/interface/lte/monitor lte1 once',
        '/interface/lte/monitor lte2 once',
    ]
    try:
        before = [router_call(router, command) for command in commands]
        smoke = ping_smoke(cfg)
        after = [router_call(router, command) for command in commands]
    finally:
        router.close()
    joined = "\n".join(x.get("stdout", "") for x in before + after)
    mangle = next((x.get("stdout", "") for x in after if "firewall/mangle/print detail" in x.get("command", "")), "")
    checks = {
        "queue_type_present": spec["queue_type"] in joined,
        "queue_kind_present": spec["queue_kind"] in joined,
        "required_options_present": all(item in joined for item in spec["required"]),
        "lte1_tree_present": "ELMO-EXP2B-LTE1" in joined and "parent=lte1" in joined and "packet-mark=elmo-exp2b-lte1" in joined,
        "lte2_tree_present": "ELMO-EXP2B-LTE2" in joined and "parent=lte2" in joined and "packet-mark=elmo-exp2b-lte2" in joined,
        "max_limit_5m_present": "max-limit=5M" in joined or "max-limit=5 000 000" in joined,
        "fasttrack_disabled": "fasttrack-connection" not in next((x.get("stdout", "") for x in after if "firewall/filter" in x.get("command", "")), ""),
        "mangle_order_lte1": mangle.find("test packet mark lte1") != -1 and mangle.find("test packet mark lte1") < mangle.find("source via lte1"),
        "mangle_order_lte2": mangle.find("test packet mark lte2") != -1 and mangle.find("test packet mark lte2") < mangle.find("source via lte2"),
        "smoke_ping_ok": all(v.get("rc") == 0 for v in smoke["paths"].values()),
    }
    # Verify at least one queue or mangle counter incremented after smoke.
    for tree in ("LTE1", "LTE2"):
        before_stdout = next((x.get("stdout", "") for x in before if f"ELMO-EXP2B-{tree}" in x.get("command", "") and "stats" in x.get("command", "")), "")
        after_stdout = next((x.get("stdout", "") for x in after if f"ELMO-EXP2B-{tree}" in x.get("command", "") and "stats" in x.get("command", "")), "")
        b = parse_counter_stdout(before_stdout)
        a = parse_counter_stdout(after_stdout)
        checks[f"queue_counter_increment_{tree.lower()}"] = a.get("packets", 0) > b.get("packets", 0) or a.get("bytes", 0) > b.get("bytes", 0)
    result = {
        "condition": condition,
        "timestamp_utc": utc_now(),
        "commands_before_smoke": before,
        "smoke": smoke,
        "commands_after_smoke": after,
        "checks": checks,
        "ok": all(checks.values()),
    }
    save_json(PUBLIC / f"verify_condition_{condition}_{suffix}.json", result)
    if not result["ok"]:
        raise RuntimeError(f"Condition {condition} verification failed: {checks}")
    return result


def kill_stale_processes() -> dict[str, Any]:
    pat = re.compile(r"(ltap_public_test\.py|iperf3|ping -n -D -O -I 192\.168\.101)")
    ps = run(["ps", "-eo", "pid=,cmd="], timeout=5)
    matches = []
    for line in ps.stdout.splitlines():
        if pat.search(line) and "exp2b_dual_rerun.py" not in line:
            pid = int(line.strip().split(None, 1)[0])
            matches.append({"pid": pid, "cmd": line.strip()})
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    if matches:
        time.sleep(2)
        for item in matches:
            try:
                os.kill(item["pid"], 0)
            except ProcessLookupError:
                continue
            try:
                os.kill(item["pid"], signal.SIGKILL)
                item["killed"] = True
            except ProcessLookupError:
                pass
    result = {"timestamp_utc": utc_now(), "matches": matches}
    save_json(PUBLIC / "stale_process_cleanup.json", result)
    return result


def port_preflight(server: str, source_ip: str, port: int) -> dict[str, Any]:
    cmd = [
        "iperf3",
        "-c",
        server,
        "-p",
        str(port),
        "-4",
        "-B",
        source_ip,
        "-u",
        "-b",
        "256K",
        "-l",
        "1200",
        "-t",
        "1",
        "-J",
    ]
    started = utc_now()
    try:
        cp = run(cmd, timeout=8)
        parsed: dict[str, Any] = {}
        error = None
        try:
            parsed = json.loads(cp.stdout or "{}")
            error = parsed.get("error")
        except json.JSONDecodeError as exc:
            error = f"json parse failed: {exc}"
        ok = cp.returncode == 0 and not error and isinstance((parsed.get("end") or {}).get("sum_received"), dict)
        return {
            "source_ip": source_ip,
            "server": server,
            "port": port,
            "started_utc": started,
            "cmd": shlex.join(cmd),
            "rc": cp.returncode,
            "ok": ok,
            "error": error,
            "stderr": sanitize_text(cp.stderr),
        }
    except Exception as exc:
        return {"source_ip": source_ip, "server": server, "port": port, "started_utc": started, "ok": False, "error": repr(exc)}


def select_endpoint_pair(cfg: dict[str, Any], used_pairs: set[tuple[int, int]], condition: str, attempt: int) -> dict[str, Any]:
    campaign = load_json(CAMPAIGN)
    server = campaign["server_ipv4"]
    lte1_ports = [p for p in campaign["ports"] if int(p) % 2 == 1]
    lte2_ports = [p for p in campaign["ports"] if int(p) % 2 == 0]
    records = []
    for p1, p2 in zip(lte1_ports, lte2_ports):
        pair = (int(p1), int(p2))
        if pair in used_pairs:
            continue
        r1 = port_preflight(server, cfg["paths"]["lte1"]["source_ip"], int(p1))
        r2 = port_preflight(server, cfg["paths"]["lte2"]["source_ip"], int(p2))
        records.append({"pair": {"lte1": int(p1), "lte2": int(p2)}, "lte1": r1, "lte2": r2})
        if r1.get("ok") and r2.get("ok"):
            result = {
                "condition": condition,
                "attempt": attempt,
                "server_hostname": campaign.get("server_hostname"),
                "server_ipv4": server,
                "selected": {"lte1": int(p1), "lte2": int(p2)},
                "records": records,
            }
            save_json(PUBLIC / "endpoint_preflight" / f"{condition}_attempt{attempt}.json", result)
            return result
        used_pairs.add(pair)
    result = {
        "condition": condition,
        "attempt": attempt,
        "server_hostname": campaign.get("server_hostname"),
        "server_ipv4": server,
        "selected": None,
        "records": records,
    }
    save_json(PUBLIC / "endpoint_preflight" / f"{condition}_attempt{attempt}.json", result)
    raise RuntimeError(f"No usable endpoint pair for {condition} attempt {attempt}")


def write_campaign(condition: str, attempt: int, path_name: str, port: int) -> Path:
    campaign = load_json(CAMPAIGN)
    path = RUNTIME / "campaigns" / f"{condition}_attempt{attempt}_{path_name}_{port}.json"
    obj = {
        "created_local": local_now(),
        "server_hostname": campaign.get("server_hostname"),
        "server_ipv4": campaign.get("server_ipv4"),
        "all_resolved_ipv4": campaign.get("all_resolved_ipv4") or [campaign.get("server_ipv4")],
        "ports": [port],
        "note": "Exp2b dual repair single-port campaign generated after endpoint preflight.",
    }
    save_json(path, obj)
    return path


def collector_cmd(path_name: str, tag: str, campaign: Path) -> list[str]:
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
        "6M",
        "--packet-length",
        "1200",
        "--duration",
        "300",
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


def queue_sampler(router: Any, run_id: str, stop: threading.Event) -> None:
    commands = {
        "queue_lte1": '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE1"',
        "queue_lte2": '/queue/tree/print stats detail where name="ELMO-EXP2B-LTE2"',
        "resource": "/system/resource/print",
    }
    path = PUBLIC / "queue_telemetry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        while not stop.is_set():
            row = {"timestamp_utc": utc_now(), "run_id": run_id}
            for name, command in commands.items():
                row[name] = router_call(router, command, timeout=8)
            f.write(json.dumps(sanitize_obj(row), ensure_ascii=True) + "\n")
            f.flush()
            stop.wait(1.0)


def run_dual_attempt(cfg: dict[str, Any], condition: str, attempt: int, endpoints: dict[str, Any]) -> dict[str, Any]:
    tag = f"{condition}_dual_6M_repair" if attempt == 1 else f"{condition}_dual_6M_repair_retry{attempt - 1}"
    ports = endpoints["selected"]
    campaigns = {
        "lte1": write_campaign(condition, attempt, "lte1", ports["lte1"]),
        "lte2": write_campaign(condition, attempt, "lte2", ports["lte2"]),
    }
    commands = {path_name: collector_cmd(path_name, tag, campaigns[path_name]) for path_name in ("lte1", "lte2")}
    logs = RUNTIME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    router = collector.RouterSSH(cfg["router"])
    stop = threading.Event()
    sampler = threading.Thread(target=queue_sampler, args=(router, tag, stop), daemon=True)
    sampler.start()
    procs: dict[str, Any] = {}
    starts: dict[str, float] = {}
    started_utc: dict[str, str] = {}
    try:
        for path_name in ("lte1", "lte2"):
            stdout = (logs / f"{tag}_{path_name}.stdout").open("w", encoding="utf-8")
            stderr = (logs / f"{tag}_{path_name}.stderr").open("w", encoding="utf-8")
            starts[path_name] = time.time()
            started_utc[path_name] = utc_now()
            procs[path_name] = {
                "proc": subprocess.Popen(commands[path_name], cwd=REPO, stdout=stdout, stderr=stderr, text=True),
                "stdout": stdout,
                "stderr": stderr,
            }
        exit_codes: dict[str, int] = {}
        for path_name, item in procs.items():
            exit_codes[path_name] = item["proc"].wait()
            item["stdout"].close()
            item["stderr"].close()
    finally:
        stop.set()
        sampler.join(timeout=10)
        router.close()
        for item in procs.values():
            if item["proc"].poll() is None:
                item["proc"].send_signal(signal.SIGINT)
                try:
                    item["proc"].wait(timeout=5)
                except subprocess.TimeoutExpired:
                    item["proc"].kill()
            if not item["stdout"].closed:
                item["stdout"].close()
            if not item["stderr"].closed:
                item["stderr"].close()
    skew = abs(starts["lte2"] - starts["lte1"])
    sanitize_tree(PUBLIC / "runs")
    sanitize_tree(RUNTIME / "logs")
    status = {
        "condition": condition,
        "run_id": tag,
        "attempt": attempt,
        "started_utc": started_utc,
        "start_skew_seconds": skew,
        "server_ipv4": endpoints["server_ipv4"],
        "server_hostname": endpoints.get("server_hostname"),
        "ports": ports,
        "commands": {path_name: shlex.join(cmd) for path_name, cmd in commands.items()},
        "exit_codes": exit_codes,
        "summaries": find_summaries(tag),
    }
    status["validation"] = validate_dual_status(status)
    status["ok"] = status["validation"]["ok"]
    save_json(PUBLIC / "run_status" / f"{tag}.json", status)
    return status


def find_summaries(tag: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for summary_path in sorted((PUBLIC / "runs").glob(f"*_{tag}_*/summary.json")):
        try:
            summary = load_json(summary_path)
        except Exception:
            continue
        path_name = ((summary.get("test") or {}).get("path") or summary_path.parent.name).strip()
        out[path_name] = {"path": str(summary_path), "summary": summary}
    return out


def validate_dual_status(status: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if status.get("start_skew_seconds", 999) > 2:
        reasons.append("START_SKEW_GT_2S")
    for path_name in ("lte1", "lte2"):
        if status["exit_codes"].get(path_name) != 0:
            reasons.append(f"{path_name.upper()}_EXIT_{status['exit_codes'].get(path_name)}")
        item = (status.get("summaries") or {}).get(path_name)
        if not item:
            reasons.append(f"{path_name.upper()}_MISSING_SUMMARY")
            continue
        summary = item["summary"]
        iperf = summary.get("iperf") or {}
        if iperf.get("error"):
            reasons.append(f"{path_name.upper()}_IPERF_ERROR")
        for key in ("mbps", "lost_percent", "jitter_ms"):
            if iperf.get(key) is None:
                reasons.append(f"{path_name.upper()}_MISSING_{key.upper()}")
        if not str(summary.get("path_verification", "")).startswith("PASS"):
            reasons.append(f"{path_name.upper()}_PATH_VERIFY_{summary.get('path_verification')}")
        observed_port = ((summary.get("test") or {}).get("server_port"))
        expected_port = status["ports"].get(path_name)
        if observed_port != expected_port:
            reasons.append(f"{path_name.upper()}_PORT_MISMATCH")
    server_failure = any("EXIT_" in r or "IPERF_ERROR" in r or "MISSING_Mbps".upper() in r for r in reasons)
    classification = "VALID" if not reasons else ("INVALID_SERVER_FAILURE" if server_failure else "INVALID")
    return {"ok": not reasons, "classification": classification, "reasons": reasons}


def metric_row(status: dict[str, Any], path_name: str) -> dict[str, Any]:
    item = (status.get("summaries") or {}).get(path_name) or {}
    summary = item.get("summary") or {}
    iperf = summary.get("iperf") or {}
    ping = summary.get("ping") or {}
    detailed_ping = ping_detail(summary_item=item)
    queue = queue_detail(status["run_id"], path_name)
    radio = summary.get("radio_target") or {}
    return {
        "condition": status["condition"],
        "run_id": status["run_id"],
        "valid": status.get("ok"),
        "path": path_name,
        "server": status.get("server_ipv4"),
        "port": status.get("ports", {}).get(path_name),
        "start_skew_seconds": status.get("start_skew_seconds"),
        "receiver_mbps": iperf.get("mbps"),
        "udp_loss_percent": iperf.get("lost_percent"),
        "udp_jitter_ms": iperf.get("jitter_ms"),
        "ping_avg_ms": ping.get("avg_ms"),
        "ping_p50_ms": detailed_ping.get("p50_ms"),
        "ping_p95_ms": ping.get("p95_ms"),
        "ping_p99_ms": detailed_ping.get("p99_ms"),
        "ping_max_ms": ping.get("max_ms"),
        "ping_loss_percent": ping.get("loss_percent"),
        "ping_samples_gt_100ms_percent": detailed_ping.get("gt_100ms_percent"),
        "ping_samples_gt_300ms_percent": detailed_ping.get("gt_300ms_percent"),
        "ping_samples_gt_1000ms_percent": detailed_ping.get("gt_1000ms_percent"),
        "longest_ping_gt_100ms_seconds": detailed_ping.get("longest_gt_100ms_seconds"),
        "longest_ping_gt_300ms_seconds": detailed_ping.get("longest_gt_300ms_seconds"),
        "longest_ping_gt_1000ms_seconds": detailed_ping.get("longest_gt_1000ms_seconds"),
        "queue_p95_queued_bytes": queue.get("p95_queued_bytes"),
        "queue_max_queued_bytes": queue.get("max_queued_bytes"),
        "queue_p95_queued_packets": queue.get("p95_queued_packets"),
        "queue_max_queued_packets": queue.get("max_queued_packets"),
        "queue_drop_delta": queue.get("drop_delta"),
        "cpu_avg_percent": queue.get("cpu_avg_percent"),
        "cpu_p95_percent": queue.get("cpu_p95_percent"),
        "cpu_max_percent": queue.get("cpu_max_percent"),
        "primary_bands_seen": "|".join(radio.get("primary_bands_seen") or []),
        "ca_bands_seen": "|".join(radio.get("ca_bands_seen") or []),
        "cell_changes": radio.get("cell_changes"),
        "path_verification": summary.get("path_verification"),
        "test_dir": str(Path(item.get("path", "")).parent) if item.get("path") else "",
        "invalid_reasons": "|".join((status.get("validation") or {}).get("reasons") or []),
    }


def ping_detail(summary_item: dict[str, Any]) -> dict[str, Any]:
    samples = ping_samples(summary_item)
    vals = [v for _, v in samples if v is not None]
    total = len(samples)

    def pct_over(threshold: float) -> float | None:
        if not total:
            return None
        return round(100.0 * sum(1 for _, v in samples if v is None or v > threshold) / total, 4)

    def longest_over(threshold: float) -> int | None:
        if not samples:
            return None
        longest = 0
        current_start: int | None = None
        current_end: int | None = None
        for sec, val in samples:
            bad = val is None or val > threshold
            if bad:
                if current_start is None:
                    current_start = sec
                current_end = sec
                longest = max(longest, (current_end - current_start) + 1)
            else:
                current_start = None
                current_end = None
        return longest

    return {
        "p50_ms": percentile(vals, 50),
        "p99_ms": percentile(vals, 99),
        "gt_100ms_percent": pct_over(100),
        "gt_300ms_percent": pct_over(300),
        "gt_1000ms_percent": pct_over(1000),
        "longest_gt_100ms_seconds": longest_over(100),
        "longest_gt_300ms_seconds": longest_over(300),
        "longest_gt_1000ms_seconds": longest_over(1000),
    }


def ping_samples(summary_item: dict[str, Any]) -> list[tuple[int, float | None]]:
    path = Path(summary_item.get("path", "")).parent / "ping.txt"
    if not path.exists():
        return []
    samples: list[tuple[int, float | None]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\[([0-9.]+)\].*time=([0-9.]+)\s*ms", line)
        if m:
            samples.append((int(float(m.group(1))), float(m.group(2))))
            continue
        m = re.match(r"\[([0-9.]+)\].*no answer", line)
        if m:
            samples.append((int(float(m.group(1))), None))
    return samples


def parse_resource_stdout(stdout: str) -> dict[str, float]:
    out: dict[str, float] = {}
    compact = " ".join(stdout.splitlines())
    cpu = re.search(r"(?:^|\s)cpu-load:\s*([0-9.]+)%", compact)
    if cpu:
        out["cpu_load"] = float(cpu.group(1))
    return out


def queue_detail(run_id: str, path_name: str) -> dict[str, Any]:
    qkey = f"queue_{path_name}"
    qbytes: list[float] = []
    qpackets: list[float] = []
    drops: list[int] = []
    cpu: list[float] = []
    path = PUBLIC / "queue_telemetry.jsonl"
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("run_id") != run_id:
            continue
        qstats = parse_counter_stdout(((row.get(qkey) or {}).get("stdout")) or "")
        if "queued-bytes" in qstats:
            qbytes.append(float(qstats["queued-bytes"]))
        if "queued-packets" in qstats:
            qpackets.append(float(qstats["queued-packets"]))
        if "dropped" in qstats:
            drops.append(qstats["dropped"])
        resource = parse_resource_stdout(((row.get("resource") or {}).get("stdout")) or "")
        if "cpu_load" in resource:
            cpu.append(resource["cpu_load"])
    return {
        "p95_queued_bytes": percentile(qbytes, 95),
        "max_queued_bytes": max(qbytes) if qbytes else None,
        "p95_queued_packets": percentile(qpackets, 95),
        "max_queued_packets": max(qpackets) if qpackets else None,
        "drop_delta": (max(drops) - min(drops)) if drops else None,
        "cpu_avg_percent": round(sum(cpu) / len(cpu), 2) if cpu else None,
        "cpu_p95_percent": percentile(cpu, 95),
        "cpu_max_percent": max(cpu) if cpu else None,
    }


def diversity(status: dict[str, Any]) -> dict[str, Any]:
    if not status.get("ok"):
        return {"available": False, "reason": "run invalid"}
    lte1 = ping_samples(status["summaries"].get("lte1", {}))
    lte2 = ping_samples(status["summaries"].get("lte2", {}))
    by1: dict[int, list[float | None]] = {}
    by2: dict[int, list[float | None]] = {}
    for ts, val in lte1:
        by1.setdefault(ts, []).append(val)
    for ts, val in lte2:
        by2.setdefault(ts, []).append(val)
    seconds = sorted(set(by1) & set(by2))

    def good(vals: list[float | None]) -> bool:
        ok_vals = [v for v in vals if v is not None]
        if len(ok_vals) < max(1, len(vals) // 2):
            return False
        return percentile(ok_vals, 95) < 100

    counts = {"both_good": 0, "lte1_impaired_lte2_good": 0, "lte2_impaired_lte1_good": 0, "both_impaired": 0}
    longest_both = 0
    current_both = 0
    for sec in seconds:
        g1 = good(by1[sec])
        g2 = good(by2[sec])
        if g1 and g2:
            counts["both_good"] += 1
            current_both = 0
        elif not g1 and g2:
            counts["lte1_impaired_lte2_good"] += 1
            current_both = 0
        elif g1 and not g2:
            counts["lte2_impaired_lte1_good"] += 1
            current_both = 0
        else:
            counts["both_impaired"] += 1
            current_both += 1
            longest_both = max(longest_both, current_both)
    return {"available": True, "sampled_seconds": len(seconds), **counts, "longest_both_impaired_seconds": longest_both}


def percentile(vals: list[float], pct: float) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100) * len(ordered)) - 1))
    return ordered[idx]


def write_outputs(statuses: list[dict[str, Any]], manifest_extra: dict[str, Any]) -> None:
    rows = [metric_row(status, path_name) for status in statuses for path_name in ("lte1", "lte2")]
    fields = list(rows[0].keys()) if rows else []
    with (PUBLIC / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    valid = {status["condition"]: status for status in statuses if status.get("ok")}
    div = {condition: diversity(status) for condition, status in valid.items()}
    classification, rationale = classify(valid)
    summary = {
        "updated_utc": utc_now(),
        "statuses": statuses,
        "valid_run_ids": {condition: status["run_id"] for condition, status in valid.items()},
        "classification": classification,
        "classification_rationale": rationale,
        "diversity": div,
        "comparison_rows": rows,
    }
    save_json(PUBLIC / "comparison.json", summary)
    manifest = {
        "experiment": "ELMO Experiment 2b simultaneous dual-load B/C repair rerun",
        "created_utc": utc_now(),
        "git_commit": run(["git", "rev-parse", "HEAD"], timeout=5).stdout.strip(),
        "collector_version": getattr(collector, "VERSION", "unknown"),
        "result_dir": str(PUBLIC.relative_to(REPO)),
        "source_repo": str(REPO),
        "conditions": ["B", "C"],
        "duration_seconds": 300,
        "bitrate_per_path": "6M",
        "packet_length_bytes": 1200,
        "rsc_import_authorization": "Madis explicitly authorized OpenClaw to import existing PFIFO/CAKE RSC files for this task.",
        **manifest_extra,
    }
    save_json(PUBLIC / "experiment_manifest.json", manifest)
    report = [
        "# ELMO Experiment 2b Dual Repair Rerun",
        "",
        f"Updated: {summary['updated_utc']}",
        f"Classification: {classification}",
        "",
        "## Runs",
        "",
    ]
    for status in statuses:
        state = "VALID" if status.get("ok") else status.get("validation", {}).get("classification", "INVALID")
        report.append(f"- {status['run_id']}: {state}; ports lte1={status.get('ports', {}).get('lte1')} lte2={status.get('ports', {}).get('lte2')}; skew={status.get('start_skew_seconds'):.3f}s")
        for path_name in ("lte1", "lte2"):
            row = metric_row(status, path_name)
            report.append(
                f"  - {path_name}: Mbps={row['receiver_mbps']} loss={row['udp_loss_percent']}% "
                f"jitter={row['udp_jitter_ms']}ms ping_avg={row['ping_avg_ms']}ms "
                f"p50={row['ping_p50_ms']}ms p95={row['ping_p95_ms']}ms "
                f"p99={row['ping_p99_ms']}ms max={row['ping_max_ms']}ms "
                f"ping_loss={row['ping_loss_percent']}% "
                f"queue_drop_delta={row['queue_drop_delta']} cpu_p95={row['cpu_p95_percent']}%"
            )
        if not status.get("ok"):
            report.append(f"  - invalid reasons: {', '.join(status.get('validation', {}).get('reasons') or [])}")
    report.extend([
        "",
        "## Diversity",
        "",
    ])
    for condition, data in div.items():
        report.append(f"- {condition}: {json.dumps(data, sort_keys=True)}")
    report.extend([
        "",
        "## Interpretation Boundary",
        "",
        "This is receiver-confirmed iPerf, path-bound ping, LTE telemetry, queue telemetry, and RouterOS resource evidence.",
        "It is not production GCC/video frame-age evidence and must not be described as proving displayed video latency is fixed.",
        "",
        f"Rationale: {rationale}",
    ])
    (PUBLIC / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def classify(valid: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if "B" not in valid or "C" not in valid:
        return "INCONCLUSIVE_DUAL_SERVER_RELIABILITY", "Could not obtain valid dual runs for both B and C."
    rows = {condition: [metric_row(status, p) for p in ("lte1", "lte2")] for condition, status in valid.items()}
    b_p95 = [r["ping_p95_ms"] for r in rows["B"] if r["ping_p95_ms"] is not None]
    c_p95 = [r["ping_p95_ms"] for r in rows["C"] if r["ping_p95_ms"] is not None]
    b_p99 = [r["ping_p99_ms"] for r in rows["B"] if r["ping_p99_ms"] is not None]
    c_p99 = [r["ping_p99_ms"] for r in rows["C"] if r["ping_p99_ms"] is not None]
    b_max = [r["ping_max_ms"] for r in rows["B"] if r["ping_max_ms"] is not None]
    c_max = [r["ping_max_ms"] for r in rows["C"] if r["ping_max_ms"] is not None]
    if not b_p95 or not c_p95:
        return "INCONCLUSIVE_DUAL_SERVER_RELIABILITY", "Missing latency metrics despite valid run status."
    b_tail = max(b_p95)
    c_tail = max(c_p95)
    b_p99_tail = max(b_p99 or b_p95)
    c_p99_tail = max(c_p99 or c_p95)
    b_max_tail = max(b_max or b_p95)
    c_max_tail = max(c_max or c_p95)
    if c_tail < 0.75 * b_tail and c_p99_tail < 0.85 * b_p99_tail:
        return (
            "CAKE_ADDS_VALUE_DUAL",
            f"C reduced worst-path p95 from {b_tail:.1f} ms to {c_tail:.1f} ms and p99 from "
            f"{b_p99_tail:.1f} ms to {c_p99_tail:.1f} ms. Max RTT was B {b_max_tail:.1f} ms vs C {c_max_tail:.1f} ms, "
            "so the claim is latency-tail improvement, not complete elimination of isolated spikes.",
        )
    if abs(c_tail - b_tail) <= max(20.0, 0.15 * b_tail):
        return "NO_MEANINGFUL_DIFFERENCE_DUAL", f"Worst-path p95 was similar: B {b_tail:.1f} ms vs C {c_tail:.1f} ms."
    return "INCONCLUSIVE_DUAL_RADIO_VARIABILITY", f"Latency tails differed under the same 5M cap, but not consistently enough for a narrow CAKE claim: B p95 {b_tail:.1f} ms vs C p95 {c_tail:.1f} ms."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args()

    PUBLIC.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cfg = load_json(CONFIG)
    campaign = load_json(CAMPAIGN)
    manifest_extra = {
        "server_hostname": campaign.get("server_hostname"),
        "server_ipv4": campaign.get("server_ipv4"),
        "available_ports": campaign.get("ports"),
    }
    save_json(PUBLIC / "initial_state.json", {
        "timestamp_utc": utc_now(),
        "git_status": run(["git", "status", "--short", "--branch"], timeout=5).stdout,
        "head": run(["git", "log", "-1", "--oneline"], timeout=5).stdout.strip(),
    })
    kill_stale_processes()
    statuses: list[dict[str, Any]] = []
    used_pairs: set[tuple[int, int]] = set()
    for condition in ("B", "C"):
        if not args.skip_import:
            import_condition(cfg, condition)
        verify_condition(cfg, condition, "pre")
        condition_ok = False
        for attempt in range(1, args.max_attempts + 1):
            endpoints = select_endpoint_pair(cfg, used_pairs, condition, attempt)
            used_pairs.add((endpoints["selected"]["lte1"], endpoints["selected"]["lte2"]))
            status = run_dual_attempt(cfg, condition, attempt, endpoints)
            statuses.append(status)
            write_outputs(statuses, manifest_extra)
            if status.get("ok"):
                condition_ok = True
                break
            if (status.get("validation") or {}).get("classification") != "INVALID_SERVER_FAILURE":
                break
        if not condition_ok:
            write_outputs(statuses, manifest_extra)
            sanitize_tree(PUBLIC)
            return 3
    write_outputs(statuses, manifest_extra)
    sanitize_tree(PUBLIC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
