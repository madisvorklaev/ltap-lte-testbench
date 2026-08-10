#!/usr/bin/env python3
"""Controlled FG621 firmware A/B test with thick pigtails."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import mixed_lte6_thick_pigtails_pre_firmware as thick


base = thick.base
CAMPAIGN_ID = "fg621-firmware-ab-thick-pigtails"
BRANCH = "fg621-firmware-ab-thick-pigtails"
TARGET_VERSION = "7.24rc3"
EXPECTED_LTE1_MODEL = "R11e-LTE6"
EXPECTED_LTE1_FIRMWARE = "R11e-LTE6_V034"
EXPECTED_LTE2_MODEL = "FG621-EA"
EXPECTED_LTE2_FIRMWARE = "16121.1034.00.01.01.04"
PRE_CAMPAIGN_ID = "mixed-lte6-thick-pigtails-pre-firmware"

REPO = base.REPO
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
PUBLIC = REPO / "results-public" / CAMPAIGN_ID
STOP_FILE = REPO / "runtime/STOP_FG621_FIRMWARE_AB_THICK_PIGTAILS"

base.CAMPAIGN_ID = CAMPAIGN_ID
base.RUNTIME = RUNTIME
base.PUBLIC = PUBLIC
base.STOP_FILE = STOP_FILE
base.BRANCH = BRANCH
base.TARGET_VERSION = TARGET_VERSION
base.TERMINAL_ITEM_STATES = set(base.TERMINAL_ITEM_STATES) | {"SKIPPED_NOT_TRIGGERED"}

thick.CAMPAIGN_ID = CAMPAIGN_ID
thick.BRANCH = BRANCH
thick.RUNTIME = RUNTIME
thick.PUBLIC = PUBLIC
thick.STOP_FILE = STOP_FILE


PRE_FG621: dict[str, dict[str, float]] = {
    "B3": {"mbps": 4.940, "loss": 17.532, "p95": 122.0, "rsrp": -94.0, "sinr": 3.0},
    "B8": {"mbps": 5.941, "loss": 0.955, "p95": 41.7, "rsrp": -91.0, "sinr": 8.0},
    "B7": {"mbps": 5.573, "loss": 7.096, "p95": 104.0, "rsrp": -105.0, "sinr": 13.0},
}

PRE_R11E: dict[str, dict[str, float]] = {
    "F1": {"loss": 0.206, "p95": 42.8},
    "F2": {"loss": 0.128, "p95": 35.5},
    "F3": {"loss": 0.778, "p95": 41.7},
}


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def compact(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def parse_key_values(raw: str) -> dict[str, str]:
    out: dict[str, str] = {"raw": raw}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip().lower().replace(" ", "_")] = value.strip()
    return out


def normalize_fw(value: str | None) -> str:
    return (value or "").strip().strip('"')


def metric(summary: dict[str, Any], path_name: str, name: str) -> Any:
    ps = summary.get(path_name) or {}
    if name == "mbps":
        return (ps.get("iperf") or {}).get("mbps")
    if name == "loss":
        return (ps.get("iperf") or {}).get("lost_percent")
    if name == "p95":
        return (ps.get("ping") or {}).get("p95_ms")
    return (ps.get("radio_target") or {}).get(name)


def item_summary(item_id: str) -> dict[str, Any]:
    return base.load_json(PUBLIC / "runs" / item_id / "summary.json", {})


def items() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {
            "id": "F1",
            "phase": "POST_FIRMWARE_F1_B3_B3",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "3",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
        },
        {
            "id": "F2",
            "phase": "POST_FIRMWARE_F2_B3_B8",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "8",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
        },
        {
            "id": "F3",
            "phase": "POST_FIRMWARE_F3_B3_B7",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "7",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
        },
    ]
    for repeat in range(1, 4):
        out.append({
            "id": f"L3-{repeat}",
            "phase": "CONDITIONAL_LONG_B3_B3",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "3",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 600,
            "packet_length": 1200,
            "required": False,
        })
    for repeat in range(1, 4):
        out.append({
            "id": f"L8-{repeat}",
            "phase": "CONDITIONAL_LONG_B3_B8",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "8",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 600,
            "packet_length": 1200,
            "required": False,
        })
    for rate in ("4M", "6M", "8M", "10M", "12M"):
        out.append({
            "id": f"STAIR-{rate}",
            "phase": "CONDITIONAL_FG621_B3_STAIRCASE",
            "mode": "single",
            "path": "lte2",
            "lte1_band": None,
            "lte2_band": "3",
            "bitrate": rate,
            "duration": 60,
            "packet_length": 1200,
            "required": False,
        })
    return out


def item_map() -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in items()}


base.items = items
base.item_map = item_map
thick.items = items
thick.item_map = item_map


def staged_secret_hits() -> list[str]:
    scan = base.run([
        "bash",
        "-lc",
        "git diff --cached --name-only -z | xargs -0 rg -n -i '\\b(password|imsi|imei|iccid|uicc|serial-number|software-id)\\b|private key' || true",
    ], timeout=30)
    return [
        line for line in scan.stdout.splitlines()
        if not line.startswith("tools/fg621_firmware_ab_thick_pigtails.py:")
    ]


class Runner(thick.Runner):
    def load_or_init_progress(self) -> dict[str, Any]:
        loaded = base.load_json(self.progress_path)
        if loaded:
            return loaded
        now_s = utcnow()
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
            "pre_campaign": PRE_CAMPAIGN_ID,
            "intended_permanent_change": "FG621-EA firmware on lte2 only",
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
            "firmware_before": None,
            "firmware_after": None,
            "firmware_category": None,
            "items": {x["id"]: {"state": "PENDING", "attempts": 0, "history": []} for x in items()},
            "last_pushed_commit": None,
            "worker_progress_counter": 0,
            "worker_last_progress_at": now_s,
        }
        self.save_progress(progress)
        return progress

    def write_manifest(self) -> None:
        lines = [
            f"# Manifest {CAMPAIGN_ID}",
            "",
            f"- A-side reference: `{PRE_CAMPAIGN_ID}`",
            "- Permanent change intended: FG621-EA firmware on `lte2` only.",
            "- R11e-LTE6 on `lte1` remains firmware/control path.",
            "- RouterOS/RouterBOARD firmware must remain 7.24rc3.",
            "- Thick beige pigtails remain installed on both modems.",
        ]
        (PUBLIC / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def verify_baseline(self) -> bool:
        ok = super().verify_baseline()
        if not ok and self.progress.get("state") not in {"BLOCKED_ROUTEROS_MISMATCH", "BLOCKED_FIRMWARE_MISMATCH", "BLOCKED_TOPOLOGY_MISMATCH"}:
            self.progress["state"] = "BLOCKED_BASELINE_MISMATCH"
            self.save_progress()
        return ok

    def firmware_query(self) -> dict[str, Any]:
        self.progress["state"] = "FIRMWARE_QUERY"
        self.save_progress()
        cp = self.router_call("/interface/lte/firmware-upgrade lte2", timeout=60)
        data = parse_key_values(cp.stdout + ("\n" + cp.stderr if cp.stderr else ""))
        data.update({
            "interface": "lte2",
            "queried_at": utcnow(),
            "returncode": cp.returncode,
        })
        base.atomic_write_json(PUBLIC / "FIRMWARE_BEFORE.json", base.sanitize_obj(data))
        if cp.returncode != 0:
            self.progress["state"] = "BLOCKED_FIRMWARE_QUERY_FAILED"
            self.last_error = cp.stderr.strip() or cp.stdout.strip() or "firmware query failed"
            self.save_progress()
            return data
        installed = normalize_fw(data.get("installed") or data.get("installed_firmware"))
        latest = normalize_fw(data.get("latest") or data.get("latest_firmware"))
        self.progress["firmware_before"] = data
        self.save_progress()
        if not latest or latest == installed:
            self.progress["state"] = "BLOCKED_NO_FG621_UPDATE"
            self.last_error = f"No newer stable FG621 firmware offered: installed={installed!r} latest={latest!r}"
            self.save_progress()
        return data

    def firmware_upgrade(self, before: dict[str, Any]) -> bool:
        if self.progress.get("state") == "BLOCKED_NO_FG621_UPDATE":
            return False
        old_fw = normalize_fw(before.get("installed") or before.get("installed_firmware") or EXPECTED_LTE2_FIRMWARE)
        latest = normalize_fw(before.get("latest") or before.get("latest_firmware"))
        self.progress["state"] = "FIRMWARE_UPGRADE_START"
        self.progress["firmware_upgrade_started_at"] = utcnow()
        self.save_progress()
        try:
            cp = self.router_call("/interface/lte/firmware-upgrade lte2 upgrade=yes", timeout=120)
        except subprocess.TimeoutExpired as exc:
            self.progress["state"] = "WAIT_FG621_REAPPEAR"
            self.progress["firmware_upgrade_command_timeout"] = {
                "at": utcnow(),
                "timeout_s": exc.timeout,
                "note": "RouterOS command timed out locally; do not start another upgrade blindly.",
            }
            self.save_progress()
            return self.recover_firmware_upgrade()
        combined = (cp.stdout + "\n" + cp.stderr).lower()
        if cp.returncode != 0:
            if "routeros" in combined and ("upgrade" in combined or "update" in combined or "required" in combined):
                self.progress["state"] = "BLOCKED_ROUTEROS_REQUIRED_FOR_MODEM_UPDATE"
            else:
                self.progress["state"] = "FAILED_FIRMWARE_UPGRADE_COMMAND"
            self.last_error = cp.stderr.strip() or cp.stdout.strip()
            self.save_progress()
            return False

        self.progress["state"] = "FIRMWARE_UPGRADING"
        self.progress["firmware_upgrade_command_stdout"] = cp.stdout.strip()
        self.save_progress()
        deadline = time.time() + 20 * 60
        restart_observed = False
        seen_missing = False
        while time.time() < deadline:
            self.progress["state"] = "WAIT_FG621_REAPPEAR"
            self.save_progress()
            mon = self.monitor("lte2")
            status = str(mon.get("status", "")).lower()
            revision = normalize_fw(mon.get("revision"))
            if not mon or status not in base.REGISTERED_LTE_STATES:
                seen_missing = True
                time.sleep(10)
                continue
            if revision and revision != old_fw:
                restart_observed = seen_missing or True
                after = self.query_after(old_fw, latest, revision, restart_observed)
                self.progress["firmware_after"] = after
                self.progress["state"] = "VERIFY_NEW_FIRMWARE"
                self.save_progress()
                return True
            time.sleep(10)
        self.progress["state"] = "FAILED_FG621_REAPPEAR_TIMEOUT"
        self.last_error = "FG621 did not reappear with changed firmware within 20 minutes"
        self.save_progress()
        return False

    def recover_firmware_upgrade(self) -> bool:
        before = self.progress.get("firmware_before") or {}
        old_fw = normalize_fw(before.get("installed") or before.get("installed_firmware") or EXPECTED_LTE2_FIRMWARE)
        latest = normalize_fw(before.get("latest") or before.get("latest_firmware"))
        started = self.progress.get("firmware_upgrade_started_at") or utcnow()
        self.progress["state"] = "WAIT_FG621_REAPPEAR"
        self.save_progress()
        deadline = time.time() + 20 * 60
        try:
            start_dt = dt.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            elapsed = (dt.datetime.now(dt.timezone.utc) - start_dt).total_seconds()
            deadline = time.time() + max(120, 20 * 60 - elapsed)
        except ValueError:
            pass
        seen_inactive = False
        while time.time() < deadline:
            mon = self.monitor("lte2")
            status = str(mon.get("status", "")).lower()
            revision = normalize_fw(mon.get("revision"))
            if not mon or status not in base.REGISTERED_LTE_STATES:
                seen_inactive = True
                time.sleep(10)
                continue
            if revision and revision != old_fw:
                after = self.query_after(old_fw, latest, revision, seen_inactive)
                self.progress["firmware_after"] = after
                self.progress["state"] = "VERIFY_NEW_FIRMWARE"
                self.save_progress()
                return True
            if revision == old_fw:
                self.progress["state"] = "FAILED_FIRMWARE_NOT_CHANGED"
                self.last_error = f"FG621 returned with unchanged firmware {old_fw}"
                self.save_progress()
                return False
            time.sleep(10)
        self.progress["state"] = "FAILED_FG621_REAPPEAR_TIMEOUT"
        self.last_error = "FG621 did not reappear with changed firmware within bounded recovery window"
        self.save_progress()
        return False

    def query_after(self, old_fw: str, latest: str, new_fw: str, restart_observed: bool) -> dict[str, Any]:
        cp = self.router_call("/interface/lte/firmware-upgrade lte2", timeout=60)
        query = parse_key_values(cp.stdout + ("\n" + cp.stderr if cp.stderr else ""))
        mon = self.monitor("lte2")
        data = {
            "interface": "lte2",
            "old_firmware": old_fw,
            "new_firmware": new_fw,
            "latest_offered_before": latest,
            "query_after": query,
            "completed_at": utcnow(),
            "registration_status": mon.get("status"),
            "monitor": base.sanitize_obj(mon),
            "modem_restart_observed": restart_observed,
        }
        base.atomic_write_json(PUBLIC / "FIRMWARE_AFTER.json", base.sanitize_obj(data))
        return data

    def run_smoke_after_upgrade(self) -> None:
        if self.progress.get("smoke_tests_completed"):
            return
        self.progress["state"] = "POST_UPGRADE_SMOKE"
        self.save_progress()
        self.set_band("lte1", "3")
        self.set_band("lte2", "3")
        time.sleep(10)
        if not self.wait_registered_for_item({"lte1_band": "3", "lte2_band": "3"}, 120)[0]:
            raise RuntimeError("smoke B3 registration failed")
        self.run_smoke_tests()

    def classify_firmware_effect(self) -> str:
        f1 = item_summary("F1")
        fg_mbps = metric(f1, "lte2", "mbps")
        fg_loss = metric(f1, "lte2", "loss")
        fg_p95 = metric(f1, "lte2", "p95")
        f2 = item_summary("F2")
        b8_mbps = metric(f2, "lte2", "mbps")
        b8_loss = metric(f2, "lte2", "loss")
        b8_p95 = metric(f2, "lte2", "p95")
        if b8_loss is not None and (b8_loss > 2 or (b8_p95 or 0) > 100 or (b8_mbps is not None and b8_mbps < 5.8)):
            return "FG621_B8_REGRESSION"
        if fg_loss is None or fg_p95 is None or fg_mbps is None:
            return "PENDING"
        if (fg_mbps >= 5.8 and fg_loss < 3 and fg_p95 < 80) or (fg_loss < 1 and fg_p95 < 60):
            return "MAJOR_B3_IMPROVEMENT"
        if fg_loss <= 8 or fg_p95 > 80:
            if fg_loss < PRE_FG621["B3"]["loss"] - 3:
                return "PARTIAL_B3_IMPROVEMENT"
        return "NO_B3_IMPROVEMENT"

    def item_should_run(self, item_id: str) -> bool:
        category = self.progress.get("firmware_category") or self.classify_firmware_effect()
        self.progress["firmware_category"] = category
        self.save_progress()
        if item_id.startswith("L3-"):
            if category == "PARTIAL_B3_IMPROVEMENT":
                return item_id in {"L3-1", "L3-2"}
            return category == "MAJOR_B3_IMPROVEMENT"
        if item_id.startswith("L8-") or item_id.startswith("STAIR-"):
            return category == "MAJOR_B3_IMPROVEMENT"
        return True

    def conclusion_label(self) -> str:
        category = self.progress.get("firmware_category") or self.classify_firmware_effect()
        control_unstable = False
        for item_id in ("F1", "F2", "F3"):
            summary = item_summary(item_id)
            loss = metric(summary, "lte1", "loss")
            p95 = metric(summary, "lte1", "p95")
            mbps = metric(summary, "lte1", "mbps")
            if loss is not None and (loss > 2 or (p95 or 0) > 100 or (mbps is not None and mbps < 5.8)):
                control_unstable = True
        if control_unstable:
            return "INCONCLUSIVE_CONTROL_PATH_UNSTABLE"
        if category == "FG621_B8_REGRESSION":
            return "FIRMWARE_REGRESSION"
        if category == "MAJOR_B3_IMPROVEMENT":
            return "FIRMWARE_FIX_CONFIRMED"
        if category == "PARTIAL_B3_IMPROVEMENT":
            return "FIRMWARE_PARTIAL_IMPROVEMENT"
        return "FIRMWARE_NO_MEANINGFUL_EFFECT"

    def update_matrix_summary(self) -> None:
        rows: list[dict[str, Any]] = []
        summary_obj: dict[str, Any] = {"campaign_id": CAMPAIGN_ID, "updated_at": utcnow(), "items": {}}
        for item_id, state in self.progress["items"].items():
            run_summary = item_summary(item_id)
            plan = item_map()[item_id]
            row = {
                "item_id": item_id,
                "state": state.get("state"),
                "attempts": state.get("attempts", 0),
                "lte1_band": plan.get("lte1_band"),
                "lte2_band": plan.get("lte2_band"),
                "dual_status": run_summary.get("dual_status"),
                "registration": state.get("registration") or run_summary.get("registration"),
            }
            for path_name in ("lte1", "lte2"):
                ps = run_summary.get(path_name) or {}
                iperf = ps.get("iperf") or {}
                ping = ps.get("ping") or {}
                radio = ps.get("radio_target") or {}
                row[f"{path_name}_mbps"] = iperf.get("mbps")
                row[f"{path_name}_loss_percent"] = iperf.get("lost_percent")
                row[f"{path_name}_jitter_ms"] = iperf.get("jitter_ms")
                row[f"{path_name}_ping_avg_ms"] = ping.get("avg_ms")
                row[f"{path_name}_ping_p95_ms"] = ping.get("p95_ms")
                row[f"{path_name}_ping_max_ms"] = ping.get("max_ms")
                row[f"{path_name}_ping_loss_percent"] = ping.get("loss_percent")
                for key in ("rssi_median", "rsrp_median", "rsrq_median", "sinr_median", "cqi_median", "ri_median", "cell_changes", "tx-queue-drop_delta"):
                    row[f"{path_name}_{key}"] = radio.get(key)
            rows.append(row)
            summary_obj["items"][item_id] = row
        PUBLIC.mkdir(parents=True, exist_ok=True)
        if rows:
            with (PUBLIC / "matrix_summary.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        base.atomic_write_json(PUBLIC / "matrix_summary.json", summary_obj)
        self.write_manifest()
        self.write_report(summary_obj)
        self.write_status(summary_obj)

    def write_report(self, summary_obj: dict[str, Any]) -> None:
        fw_before = self.progress.get("firmware_before") or {}
        fw_after = self.progress.get("firmware_after") or {}
        old_fw = normalize_fw(fw_after.get("old_firmware") or fw_before.get("installed") or EXPECTED_LTE2_FIRMWARE)
        new_fw = normalize_fw(fw_after.get("new_firmware") or "")
        latest = normalize_fw(fw_after.get("latest_offered_before") or fw_before.get("latest") or fw_before.get("latest_firmware"))
        lines = [
            f"# FG621 firmware A/B test {CAMPAIGN_ID}",
            "",
            f"Updated: {summary_obj['updated_at']}",
            "",
            f"A-side reference: `{PRE_CAMPAIGN_ID}`.",
            f"FG621 firmware before: `{old_fw}`.",
            f"Latest stable offered: `{latest}`.",
            f"FG621 firmware after: `{new_fw}`.",
            f"RouterOS: `{self.progress.get('routeros') or TARGET_VERSION}`.",
            "",
            "| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for item_id, row in summary_obj["items"].items():
            for path_name, modem in (("lte1", EXPECTED_LTE1_MODEL), ("lte2", EXPECTED_LTE2_MODEL)):
                if item_id.startswith("STAIR-") and path_name == "lte1":
                    continue
                lines.append(
                    f"| {item_id} | {modem} | {row.get(f'{path_name}_band') or ''} | "
                    f"{compact(row.get(f'{path_name}_mbps'))} | {compact(row.get(f'{path_name}_loss_percent'))} | "
                    f"{compact(row.get(f'{path_name}_ping_p95_ms'))} | {compact(row.get(f'{path_name}_rsrp_median'))} | "
                    f"{compact(row.get(f'{path_name}_sinr_median'))} | {row.get('dual_status') or row.get('registration') or row.get('state') or ''} |"
                )
        lines += [
            "",
            "## FG621 A/B",
            "",
            "| FG621 band | Pre-FW Mbps | Post-FW Mbps | Pre loss % | Post loss % | Pre p95 | Post p95 | Pre RSRP | Post RSRP | Pre SINR | Post SINR |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for band, item_id in (("B3", "F1"), ("B8", "F2"), ("B7", "F3")):
            post = item_summary(item_id)
            pre = PRE_FG621[band]
            lines.append(
                f"| {band} | {compact(pre['mbps'])} | {compact(metric(post, 'lte2', 'mbps'))} | "
                f"{compact(pre['loss'])} | {compact(metric(post, 'lte2', 'loss'))} | "
                f"{compact(pre['p95'])} | {compact(metric(post, 'lte2', 'p95'))} | "
                f"{compact(pre['rsrp'])} | {compact(metric(post, 'lte2', 'rsrp_median'))} | "
                f"{compact(pre['sinr'])} | {compact(metric(post, 'lte2', 'sinr_median'))} |"
            )
        lines += [
            "",
            "| Test | Pre R11e loss | Post R11e loss | Pre p95 | Post p95 | Control stable? |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for item_id in ("F1", "F2", "F3"):
            pre = PRE_R11E[item_id]
            post = item_summary(item_id)
            loss = metric(post, "lte1", "loss")
            p95 = metric(post, "lte1", "p95")
            stable = not (loss is not None and (loss > 2 or (p95 or 0) > 100))
            lines.append(f"| {item_id} | {compact(pre['loss'])} | {compact(loss)} | {compact(pre['p95'])} | {compact(p95)} | {stable} |")
        category = self.progress.get("firmware_category") or self.classify_firmware_effect()
        b3_post = item_summary("F1")
        b3_loss = metric(b3_post, "lte2", "loss")
        b3_p95 = metric(b3_post, "lte2", "p95")
        b3_mbps = metric(b3_post, "lte2", "mbps")
        lines += [
            "",
            "## Conclusions",
            "",
            f"1. FG621 firmware before: `{old_fw}`.",
            f"2. Latest stable offered: `{latest}`.",
            f"3. Firmware installed after: `{new_fw}`.",
            f"4. B3 category: `{category}`.",
            f"5. B3 throughput/loss/p95 delta: {compact((b3_mbps or 0) - PRE_FG621['B3']['mbps'])} Mbps, {compact((b3_loss or 0) - PRE_FG621['B3']['loss'])} pp loss, {compact((b3_p95 or 0) - PRE_FG621['B3']['p95'])} ms p95.",
            f"6. B8 remained good: `{category != 'FG621_B8_REGRESSION'}`.",
            f"7. B7 change: see B7 row above.",
            "8. R11e control stayed stable unless marked otherwise in the control table.",
            "9. Firmware attribution depends on the B3 and B8 deltas above.",
            "10. Unrestricted FG621 band selection is acceptable only if B3 no longer shows impairment.",
            "11. R11e firmware should not be tested from this campaign unless separately requested.",
            f"12. Original bands restored: `{str(bool(self.progress.get('bands_restored'))).lower()}`.",
            "",
            self.conclusion_label(),
        ]
        (PUBLIC / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_status(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# Status {CAMPAIGN_ID}",
            "",
            f"- State: {self.progress.get('state')}",
            f"- Current item: {self.progress.get('current_item') or '-'}",
            f"- Progress: {self.progress.get('completed_count')}/{self.progress.get('mandatory_total')}",
            f"- Firmware category: {self.progress.get('firmware_category')}",
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
        paths = [
            "tools/fg621_firmware_ab_thick_pigtails.py",
            "tools/ltap_firmware_ab_watchdog.py",
            f"results-public/{CAMPAIGN_ID}",
        ]
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
            if (
                self.progress.get("firmware_before")
                and not self.progress.get("firmware_after")
                and self.progress.get("state") in {"FIRMWARE_UPGRADE_START", "FIRMWARE_UPGRADING", "WAIT_FG621_REAPPEAR"}
            ):
                if not self.recover_firmware_upgrade():
                    self.update_matrix_summary()
                    self.git_checkpoint("firmware-ab: firmware recovery failed")
                    return
                self.progress["state"] = "POST_UPGRADE_TESTING"
                self.save_progress()
                self.update_matrix_summary()
                self.git_checkpoint("firmware-ab: firmware upgraded")
            if not self.progress.get("firmware_after") and not self.verify_baseline():
                self.git_checkpoint("firmware-ab: blocked baseline")
                return
            if not self.verify_lab_routes():
                self.wait_until("WAIT_NETWORK", self.verify_lab_routes, 120)
            self.save_original_bands()
            self.update_matrix_summary()
            if not self.progress.get("firmware_after"):
                self.git_checkpoint("firmware-ab: initialize")
                before = self.firmware_query()
                self.update_matrix_summary()
                self.git_checkpoint("firmware-ab: query firmware")
                if self.progress.get("state", "").startswith("BLOCKED"):
                    return
                if not self.firmware_upgrade(before):
                    self.update_matrix_summary()
                    self.git_checkpoint("firmware-ab: firmware upgrade failed or blocked")
                    return
            self.progress["state"] = "POST_UPGRADE_TESTING"
            self.last_error = ""
            self.save_progress()
            self.update_matrix_summary()
            self.git_checkpoint("firmware-ab: firmware upgraded")
            self.run_smoke_after_upgrade()
            for item in items():
                state = self.progress["items"][item["id"]].get("state")
                if state in base.TERMINAL_ITEM_STATES:
                    continue
                if STOP_FILE.exists():
                    break
                if item["id"] not in {"F1", "F2", "F3"} and not self.item_should_run(item["id"]):
                    self.transition(item["id"], "SKIPPED_NOT_TRIGGERED", attempts=0, registration="CONDITIONAL_NOT_TRIGGERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"firmware-ab: skip {item['id']}")
                    continue
                self.run_item(item)
                if item["id"] == "F1":
                    self.progress["firmware_category"] = self.classify_firmware_effect()
                    self.save_progress()
            if STOP_FILE.exists() or all(x.get("state") in base.TERMINAL_ITEM_STATES for x in self.progress["items"].values()):
                self.restore_until_verified()
                self.final_monitor_snapshots()
                self.update_matrix_summary()
                self.git_checkpoint("firmware-ab: finalize")
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
            verified, registration = self.wait_registered_for_item(item, 120)
            if not verified:
                registration_status = "B7_UNAVAILABLE_POST_FIRMWARE" if item_id == "F3" else "band did not register/verify"
                self.transition(item_id, "SKIPPED_BAND_UNAVAILABLE", attempts=attempts, bands=bands, registration=registration_status, monitor=base.sanitize_obj(registration))
                self.update_matrix_summary()
                self.git_checkpoint(f"firmware-ab: {item_id} unavailable")
                return
            self.transition(item_id, "READY", registration="REGISTERED", monitor=base.sanitize_obj(registration))
            max_attempts = 2
            while attempts < max_attempts:
                if STOP_FILE.exists():
                    return
                attempts += 1
                self.transition(item_id, "RUNNING", attempts=attempts)
                if item.get("mode") == "single":
                    ok, data = self.run_single(item, attempts)
                else:
                    ok, data = self.run_dual(item, attempts)
                data["registration"] = "REGISTERED"
                data["registration_monitor"] = base.sanitize_obj(registration)
                self.transition(item_id, "ANALYZING", attempts=attempts, dual_status=data.get("dual_status"))
                self.transition(item_id, "SANITIZING", attempts=attempts)
                self.publish_run(item_id, data)
                if ok:
                    self.transition(item_id, "COMPLETE", attempts=attempts, dual_status=data.get("dual_status"), registration="REGISTERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"firmware-ab: complete {item_id}")
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
                    self.git_checkpoint(f"firmware-ab: failed {item_id}")
                    return
        except Exception as exc:
            self.last_error = repr(exc)
            attempts += 1
            terminal = "FAILED_AFTER_RETRIES" if attempts >= 2 else "RETRY_PENDING"
            self.transition(item_id, terminal, attempts=attempts, last_error=self.last_error)
            self.update_matrix_summary()
            self.git_checkpoint(f"firmware-ab: {terminal.lower()} {item_id}")


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
