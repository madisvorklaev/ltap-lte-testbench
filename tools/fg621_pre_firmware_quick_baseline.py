#!/usr/bin/env python3
"""Quick pre-firmware baseline for swapped mixed-LTE6 LtAP setup."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import signal
import time
from pathlib import Path
from typing import Any

import mixed_lte6_matrix as base


CAMPAIGN_ID = "fg621-pre-firmware-quick-baseline"
BRANCH = "fg621-pre-firmware-quick-baseline"
TARGET_VERSION = "7.24rc3"
EXPECTED_LTE1_MODEL = "R11e-LTE6"
EXPECTED_LTE1_FIRMWARE = "R11e-LTE6_V034"
EXPECTED_LTE2_MODEL = "FG621-EA"
EXPECTED_LTE2_FIRMWARE = "16121.1034.00.01.01.04"

REPO = base.REPO
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
PUBLIC = REPO / "results-public" / CAMPAIGN_ID
STOP_FILE = REPO / "runtime/STOP_FG621_PRE_FIRMWARE_QUICK_BASELINE"

base.CAMPAIGN_ID = CAMPAIGN_ID
base.RUNTIME = RUNTIME
base.PUBLIC = PUBLIC
base.STOP_FILE = STOP_FILE
base.BRANCH = BRANCH
base.TARGET_VERSION = TARGET_VERSION


def items() -> list[dict[str, Any]]:
    return [
        {
            "id": "Q1",
            "phase": "PRE_FIRMWARE_Q1_B3_B3",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "3",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "description": "Fresh B3/B3 baseline",
        },
        {
            "id": "Q2",
            "phase": "PRE_FIRMWARE_Q2_B3_B8",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "8",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "description": "Fresh best-case B3/B8 baseline",
        },
        {
            "id": "Q3",
            "phase": "PRE_FIRMWARE_Q3_B7_AVAILABILITY",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "7",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "availability_only_until_registered": True,
            "description": "B7 availability check, one short run only if registered",
        },
    ]


def item_map() -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in items()}


base.items = items
base.item_map = item_map


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def compact_metric(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def staged_secret_hits() -> list[str]:
    scan = base.run([
        "bash",
        "-lc",
        "git diff --cached --name-only -z | xargs -0 rg -n -i '\\b(password|imsi|imei|iccid|uicc|serial-number|software-id)\\b|private key' || true",
    ], timeout=30)
    return [
        line for line in scan.stdout.splitlines()
        if not line.startswith("tools/fg621_pre_firmware_quick_baseline.py:")
    ]


class Runner(base.Runner):
    def load_or_init_progress(self) -> dict[str, Any]:
        loaded = base.load_json(self.progress_path)
        if loaded:
            return loaded
        now_s = utcnow()
        item_states = {x["id"]: {"state": "PENDING", "attempts": 0, "history": []} for x in items()}
        progress = {
            "schema_version": 1,
            "campaign_id": CAMPAIGN_ID,
            "state": "STARTING",
            "started_at": now_s,
            "updated_at": now_s,
            "routeros": None,
            "routerboard_firmware": None,
            "modem_lte1": {"expected": EXPECTED_LTE1_MODEL, "detected": None, "firmware": None},
            "modem_lte2": {"expected": EXPECTED_LTE2_MODEL, "detected": None, "firmware": None},
            "original_band_lte1": None,
            "original_band_lte2": None,
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

    def verify_baseline(self) -> bool:
        resource_cp = self.router_call("/system/resource/print", timeout=10)
        routerboard_cp = self.router_call("/system/routerboard/print", timeout=10)
        detail_cp = self.router_call("/interface/lte/print detail without-paging", timeout=15)
        lte1 = self.monitor("lte1")
        lte2 = self.monitor("lte2")

        (RUNTIME / "baseline").mkdir(parents=True, exist_ok=True)
        (RUNTIME / "baseline/system_resource.txt").write_text(resource_cp.stdout, encoding="utf-8")
        (RUNTIME / "baseline/system_routerboard.txt").write_text(routerboard_cp.stdout, encoding="utf-8")
        (RUNTIME / "baseline/interface_lte_detail.txt").write_text(detail_cp.stdout, encoding="utf-8")
        base.atomic_write_json(RUNTIME / "baseline/lte1_monitor.json", lte1)
        base.atomic_write_json(RUNTIME / "baseline/lte2_monitor.json", lte2)

        lte1_model = lte1.get("model") or self.extract_interface_model(detail_cp.stdout, "lte1")
        lte2_model = lte2.get("model") or self.extract_interface_model(detail_cp.stdout, "lte2")
        self.progress["modem_lte1"] = {"expected": EXPECTED_LTE1_MODEL, "detected": lte1_model, "firmware": lte1.get("revision")}
        self.progress["modem_lte2"] = {"expected": EXPECTED_LTE2_MODEL, "detected": lte2_model, "firmware": lte2.get("revision")}

        routeros_ok = f"version: {TARGET_VERSION}" in resource_cp.stdout
        routerboard_ok = f"current-firmware: {TARGET_VERSION}" in routerboard_cp.stdout
        lte1_ok = re.search(r"R11e-LTE6|LTE6", str(lte1_model), re.I) is not None
        lte2_ok = re.search(r"FG621|R11eL-FG621", str(lte2_model), re.I) is not None
        lte1_fw_ok = lte1.get("revision") == EXPECTED_LTE1_FIRMWARE
        lte2_fw_ok = lte2.get("revision") == EXPECTED_LTE2_FIRMWARE

        self.progress["routeros"] = TARGET_VERSION if routeros_ok else "MISMATCH"
        self.progress["routerboard_firmware"] = TARGET_VERSION if routerboard_ok else "MISMATCH"
        self.progress["baseline_verified_at"] = utcnow()
        self.save_progress()

        if all([routeros_ok, routerboard_ok, lte1_ok, lte2_ok, lte1_fw_ok, lte2_fw_ok]):
            return True

        self.progress["state"] = "BLOCKED_BASELINE_MISMATCH"
        self.last_error = (
            "BLOCKED_BASELINE_MISMATCH: "
            f"routeros_ok={routeros_ok} routerboard_ok={routerboard_ok} "
            f"lte1={self.progress['modem_lte1']} lte2={self.progress['modem_lte2']}"
        )
        self.save_progress()
        self.update_matrix_summary()
        return False

    def wait_registered_for_item(self, item: dict[str, Any], deadline_s: int) -> tuple[bool, dict[str, Any]]:
        deadline = time.time() + deadline_s
        needed = self.desired_bands(item)
        first_ok_at: str | None = None
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = {"lte1": self.monitor("lte1"), "lte2": self.monitor("lte2")}
            all_ok = True
            for iface in ("lte1", "lte2"):
                mon = last.get(iface) or {}
                if str(mon.get("status", "")).lower() not in base.REGISTERED_LTE_STATES:
                    all_ok = False
                    continue
                if not self.primary_band_allowed(mon.get("primary-band", ""), needed[iface]):
                    all_ok = False
            if all_ok:
                first_ok_at = utcnow()
                break
            time.sleep(5)
        if not first_ok_at:
            return False, last

        stable_until = time.time() + 30
        while time.time() < stable_until:
            last = {"lte1": self.monitor("lte1"), "lte2": self.monitor("lte2")}
            if any(str((last.get(iface) or {}).get("status", "")).lower() not in base.REGISTERED_LTE_STATES for iface in ("lte1", "lte2")):
                return False, last
            time.sleep(5)
        last["registration_verified_at"] = first_ok_at
        return True, last

    def collect_telemetry_medians(self, run_dir: Path, path_name: str) -> dict[str, Any]:
        values: dict[str, list[float]] = {"rsrp": [], "rsrq": [], "sinr": [], "cqi": [], "ri": []}
        tele = run_dir / f"telemetry_sanitized_{path_name}.jsonl"
        if not tele.exists():
            return {}
        with tele.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mon = data.get("lte") or data
                for src, dst in (("rsrp", "rsrp"), ("rsrq", "rsrq"), ("sinr", "sinr"), ("cqi", "cqi"), ("ri", "ri")):
                    value = mon.get(src)
                    if isinstance(value, str):
                        match = re.search(r"-?\d+(?:\.\d+)?", value)
                        value = float(match.group(0)) if match else None
                    if isinstance(value, (int, float)):
                        values[dst].append(float(value))
        return {f"{key}_median": median(series) for key, series in values.items() if series}

    def publish_run(self, item_id: str, data: dict[str, Any]) -> None:
        super().publish_run(item_id, data)
        run_dir = PUBLIC / "runs" / item_id
        summary = base.load_json(run_dir / "summary.json", {})
        for path_name in ("lte1", "lte2"):
            if summary.get(path_name):
                summary[path_name]["telemetry_medians"] = self.collect_telemetry_medians(run_dir, path_name)
        base.atomic_write_json(run_dir / "summary.json", base.sanitize_obj(summary))
        self.update_matrix_summary()

    def update_matrix_summary(self) -> None:
        rows: list[dict[str, Any]] = []
        summary_obj: dict[str, Any] = {"campaign_id": CAMPAIGN_ID, "updated_at": utcnow(), "items": {}}
        for item_id, state in self.progress["items"].items():
            run_summary = base.load_json(PUBLIC / "runs" / item_id / "summary.json", {})
            qitem = item_map()[item_id]
            row = {
                "item_id": item_id,
                "state": state.get("state"),
                "attempts": state.get("attempts", 0),
                "lte1_band": qitem["lte1_band"],
                "lte2_band": qitem["lte2_band"],
                "dual_status": run_summary.get("dual_status"),
                "registration": state.get("registration") or run_summary.get("registration"),
            }
            for path_name in ("lte1", "lte2"):
                ps = run_summary.get(path_name) or {}
                iperf = ps.get("iperf") or {}
                ping = ps.get("ping") or {}
                tele = ps.get("telemetry_medians") or {}
                row[f"{path_name}_mbps"] = iperf.get("mbps")
                row[f"{path_name}_loss_percent"] = iperf.get("lost_percent")
                row[f"{path_name}_jitter_ms"] = iperf.get("jitter_ms")
                row[f"{path_name}_ping_avg_ms"] = ping.get("avg_ms")
                row[f"{path_name}_ping_p95_ms"] = ping.get("p95_ms")
                row[f"{path_name}_ping_max_ms"] = ping.get("max_ms")
                row[f"{path_name}_ping_loss_percent"] = ping.get("loss_percent")
                row[f"{path_name}_rsrp_median"] = tele.get("rsrp_median")
                row[f"{path_name}_rsrq_median"] = tele.get("rsrq_median")
                row[f"{path_name}_sinr_median"] = tele.get("sinr_median")
            rows.append(row)
            summary_obj["items"][item_id] = row
        PUBLIC.mkdir(parents=True, exist_ok=True)
        if rows:
            with (PUBLIC / "matrix_summary.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        base.atomic_write_json(PUBLIC / "matrix_summary.json", summary_obj)
        self.write_report(summary_obj)
        self.write_status(summary_obj)

    def write_report(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# FG621 pre-firmware quick baseline {CAMPAIGN_ID}",
            "",
            f"Updated: {summary_obj['updated_at']}",
            "",
            f"FG621 firmware expected/verified before tests: `{EXPECTED_LTE2_FIRMWARE}`.",
            f"RouterOS expected/verified before tests: `{TARGET_VERSION}`.",
            "",
            "| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | Registration |",
            "|---|---|---|---:|---:|---:|---|",
        ]
        for item_id, row in summary_obj["items"].items():
            for path_name, modem in (("lte1", EXPECTED_LTE1_MODEL), ("lte2", EXPECTED_LTE2_MODEL)):
                band = row.get(f"{path_name}_band")
                lines.append(
                    f"| {item_id} | {modem} | {band} | "
                    f"{compact_metric(row.get(f'{path_name}_mbps'))} | "
                    f"{compact_metric(row.get(f'{path_name}_loss_percent'))} | "
                    f"{compact_metric(row.get(f'{path_name}_ping_p95_ms'))} | "
                    f"{row.get('registration') or row.get('state') or ''} |"
                )
        q1 = summary_obj["items"].get("Q1", {})
        q2 = summary_obj["items"].get("Q2", {})
        q3 = summary_obj["items"].get("Q3", {})
        lines += [
            "",
            "## Required Statements",
            "",
            f"- Fresh pre-upgrade FG621 B3 result: {compact_metric(q1.get('lte2_mbps'))} Mbps, {compact_metric(q1.get('lte2_loss_percent'))}% UDP loss, p95 {compact_metric(q1.get('lte2_ping_p95_ms'))} ms.",
            f"- Fresh pre-upgrade R11e-LTE6 B3 control: {compact_metric(q1.get('lte1_mbps'))} Mbps, {compact_metric(q1.get('lte1_loss_percent'))}% UDP loss, p95 {compact_metric(q1.get('lte1_ping_p95_ms'))} ms.",
            f"- Fresh pre-upgrade FG621 B8 result: {compact_metric(q2.get('lte2_mbps'))} Mbps, {compact_metric(q2.get('lte2_loss_percent'))}% UDP loss, p95 {compact_metric(q2.get('lte2_ping_p95_ms'))} ms.",
            f"- FG621 B7 availability: {q3.get('registration') or q3.get('state') or 'pending'}.",
            f"- FG621 firmware remained `{self.progress.get('modem_lte2', {}).get('firmware') or EXPECTED_LTE2_FIRMWARE}`.",
            f"- RouterOS remained `{self.progress.get('routeros') or TARGET_VERSION}`.",
            f"- Original bands restored: `{str(bool(self.progress.get('bands_restored'))).lower()}`.",
        ]
        (PUBLIC / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_status(self, summary_obj: dict[str, Any]) -> None:
        current = self.progress.get("current_item") or "-"
        lines = [
            f"# Status {CAMPAIGN_ID}",
            "",
            f"- State: {self.progress.get('state')}",
            f"- Current item: {current}",
            f"- Progress: {self.progress.get('completed_count')}/{self.progress.get('mandatory_total')}",
            f"- Bands restored: {self.progress.get('bands_restored')}",
            f"- Last error: {self.last_error or self.progress.get('last_error') or ''}",
            "",
            "| Item | State | Attempts | Status |",
            "| --- | --- | ---: | --- |",
        ]
        for item_id, row in summary_obj["items"].items():
            lines.append(f"| {item_id} | {row.get('state')} | {row.get('attempts')} | {row.get('dual_status') or row.get('registration') or ''} |")
        (PUBLIC / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def git_checkpoint(self, message: str) -> None:
        paths = ["tools/fg621_pre_firmware_quick_baseline.py", f"results-public/{CAMPAIGN_ID}"]
        base.run(["git", "add", *paths], timeout=30)
        staged = base.run(["git", "diff", "--cached", "--name-only"], timeout=30).stdout.splitlines()
        if not staged:
            return
        bad_lines = staged_secret_hits()
        if bad_lines:
            self.progress["push_pending"] = True
            self.last_error = "Secret scan blocked commit: " + "; ".join(bad_lines[:3])
            self.save_progress()
            base.run(["git", "reset"], timeout=30)
            return
        commit = base.run(["git", "commit", "-m", message], timeout=60)
        if commit.returncode not in (0, 1):
            self.progress["push_pending"] = True
            self.last_error = commit.stderr.strip()
            self.save_progress()
            return
        push = base.run(["git", "push", "-u", "origin", BRANCH], timeout=120)
        if push.returncode != 0:
            self.progress["push_pending"] = True
            self.last_error = push.stderr.strip()
        else:
            self.progress["last_pushed_commit"] = base.run(["git", "rev-parse", "HEAD"], timeout=10).stdout.strip()
            self.progress["push_pending"] = False
        self.save_progress()

    def run(self) -> None:
        self.start_heartbeat()
        try:
            if not self.verify_baseline():
                return
            if not self.verify_lab_routes():
                self.wait_until("WAIT_NETWORK", self.verify_lab_routes, 120)
            self.save_original_bands()
            if not self.server_probe():
                self.wait_until("WAIT_SERVER", self.server_probe, 600)
            self.progress["state"] = "RUNNING"
            self.save_progress()
            self.update_matrix_summary()
            self.git_checkpoint("pre-firmware-baseline: initialize")
            for item in items():
                state = self.progress["items"][item["id"]].get("state")
                if state in base.TERMINAL_ITEM_STATES:
                    continue
                if STOP_FILE.exists():
                    break
                self.run_item(item)
            if STOP_FILE.exists() or all(x.get("state") in base.TERMINAL_ITEM_STATES for x in self.progress["items"].values()):
                self.restore_until_verified()
                self.update_matrix_summary()
                self.git_checkpoint("pre-firmware-baseline: finalize")
        finally:
            self.close()

    def run_item(self, item: dict[str, Any]) -> None:
        item_id = item["id"]
        attempts = int(self.progress["items"][item_id].get("attempts", 0))
        try:
            self.transition(item_id, "APPLYING_BANDS", attempts=attempts)
            for iface, band in self.desired_bands(item).items():
                if band is not None:
                    self.set_band(iface, band)
            time.sleep(5)
            bands = self.read_band_values()
            readback_ok = all((bands[iface] or "") == band for iface, band in self.desired_bands(item).items() if band is not None)
            if not readback_ok:
                raise RuntimeError(f"band readback mismatch: {bands}")
            self.transition(item_id, "WAITING_REGISTRATION", bands=bands)

            deadline = 120 if item_id == "Q3" else 120
            verified, registration = self.wait_registered_for_item(item, deadline)
            if not verified:
                registration_status = "B7_UNAVAILABLE_PRE_FIRMWARE" if item_id == "Q3" else "band did not register/verify"
                self.transition(item_id, "SKIPPED_BAND_UNAVAILABLE", attempts=attempts, bands=bands, registration=registration_status, monitor=base.sanitize_obj(registration))
                self.update_matrix_summary()
                self.git_checkpoint(f"pre-firmware-baseline: {item_id} unavailable")
                return

            self.transition(item_id, "READY", registration="REGISTERED", monitor=base.sanitize_obj(registration))
            max_attempts = 1 if item_id == "Q3" else 2
            while attempts < max_attempts:
                if STOP_FILE.exists():
                    return
                attempts += 1
                self.transition(item_id, "RUNNING", attempts=attempts)
                ok, data = self.run_dual(item, attempts)
                data["registration"] = "REGISTERED"
                data["registration_monitor"] = base.sanitize_obj(registration)
                self.transition(item_id, "ANALYZING", attempts=attempts, dual_status=data.get("dual_status"))
                self.transition(item_id, "SANITIZING", attempts=attempts)
                self.publish_run(item_id, data)
                if ok:
                    self.transition(item_id, "COMPLETE", attempts=attempts, dual_status=data.get("dual_status"), registration="REGISTERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"pre-firmware-baseline: complete {item_id}")
                    return
                self.last_error = data.get("dual_status") or "run failed"
                if attempts < max_attempts:
                    self.transition(item_id, "RETRY_PENDING", attempts=attempts, last_error=self.last_error)
                    for _ in range(60):
                        if STOP_FILE.exists():
                            return
                        time.sleep(1)
                else:
                    self.transition(item_id, "FAILED_AFTER_RETRIES", attempts=attempts, last_error=self.last_error, registration="REGISTERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"pre-firmware-baseline: failed {item_id}")
                    return
        except Exception as exc:
            self.last_error = repr(exc)
            attempts += 1
            terminal = "FAILED_AFTER_RETRIES" if attempts >= (1 if item_id == "Q3" else 2) else "RETRY_PENDING"
            self.transition(item_id, terminal, attempts=attempts, last_error=self.last_error)
            self.update_matrix_summary()
            self.git_checkpoint(f"pre-firmware-baseline: {terminal.lower()} {item_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Resume existing campaign state")
    parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    runner = Runner()

    def handle_signal(signum: int, frame: Any) -> None:
        if signum == signal.SIGINT:
            STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            STOP_FILE.write_text(f"signal {signum} at {utcnow()}\n", encoding="utf-8")

    signal.signal(signal.SIGTERM, lambda signum, frame: base.raise_system_exit(143))
    signal.signal(signal.SIGINT, handle_signal)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
