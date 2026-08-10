#!/usr/bin/env python3
"""Thick-pigtail pre-firmware validation for swapped mixed-LTE6 LtAP setup."""

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

import fg621_pre_firmware_quick_baseline as quick


base = quick.base
CAMPAIGN_ID = "mixed-lte6-thick-pigtails-pre-firmware"
BRANCH = "mixed-lte6-thick-pigtails-pre-firmware"
TARGET_VERSION = "7.24rc3"
EXPECTED_LTE1_MODEL = "R11e-LTE6"
EXPECTED_LTE1_FIRMWARE = "R11e-LTE6_V034"
EXPECTED_LTE2_MODEL = "FG621-EA"
EXPECTED_LTE2_FIRMWARE = "16121.1034.00.01.01.04"
THIN_BASELINE_ID = "fg621-pre-firmware-quick-baseline"

REPO = base.REPO
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
PUBLIC = REPO / "results-public" / CAMPAIGN_ID
STOP_FILE = REPO / "runtime/STOP_MIXED_LTE6_THICK_PIGTAILS_PRE_FIRMWARE"
THIN_PUBLIC = REPO / "results-public" / THIN_BASELINE_ID

base.CAMPAIGN_ID = CAMPAIGN_ID
base.RUNTIME = RUNTIME
base.PUBLIC = PUBLIC
base.STOP_FILE = STOP_FILE
base.BRANCH = BRANCH
base.TARGET_VERSION = TARGET_VERSION
base.TERMINAL_ITEM_STATES = set(base.TERMINAL_ITEM_STATES) | {"SKIPPED_NOT_TRIGGERED"}

quick.CAMPAIGN_ID = CAMPAIGN_ID
quick.BRANCH = BRANCH
quick.RUNTIME = RUNTIME
quick.PUBLIC = PUBLIC
quick.STOP_FILE = STOP_FILE


THIN_REFERENCES: dict[tuple[str, str], dict[str, Any]] = {
    ("P1", "lte1"): {"modem": "R11e-LTE6", "band": "3", "mbps": 5.994, "loss": 0.079, "p95": 35.7, "rsrp": -94.0, "sinr": 10.0},
    ("P1", "lte2"): {"modem": "FG621-EA", "band": "3", "mbps": 5.326, "loss": 11.211, "p95": 123.0, "rsrp": -94.0, "sinr": 4.0},
    ("P2", "lte1"): {"modem": "R11e-LTE6", "band": "3", "mbps": 5.993, "loss": 0.097, "p95": 31.0},
    ("P2", "lte2"): {"modem": "FG621-EA", "band": "8", "mbps": 5.994, "loss": 0.078, "p95": 46.9, "rsrp": -83.0, "sinr": 5.0},
    ("P3", "lte2"): {"modem": "FG621-EA", "band": "7", "mbps": 5.799, "loss": 3.326, "p95": 137.0, "rsrp": -105.0, "sinr": 10.0},
}


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def compact(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


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
    return [
        {
            "id": "P1",
            "phase": "THICK_PIGTAIL_P1_B3_B3",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "3",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "description": "B3/B3 direct pigtail comparison",
        },
        {
            "id": "P2",
            "phase": "THICK_PIGTAIL_P2_B3_B8",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "8",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "description": "B3/B8 regression comparison",
        },
        {
            "id": "P3",
            "phase": "THICK_PIGTAIL_P3_B7_CHECK",
            "mode": "dual",
            "lte1_band": "3",
            "lte2_band": "7",
            "lte1_bitrate": "6M",
            "lte2_bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": True,
            "description": "B7 availability and optional comparison",
        },
        {
            "id": "P4",
            "phase": "THICK_PIGTAIL_P4_FG621_B3_ISOLATED",
            "mode": "single",
            "path": "lte2",
            "lte1_band": None,
            "lte2_band": "3",
            "bitrate": "6M",
            "duration": 300,
            "packet_length": 1200,
            "required": False,
            "description": "Isolated FG621 B3 confirmation only if P1 improves dramatically",
        },
    ]


def item_map() -> dict[str, dict[str, Any]]:
    return {x["id"]: x for x in items()}


base.items = items
base.item_map = item_map
quick.items = items
quick.item_map = item_map


def staged_secret_hits() -> list[str]:
    scan = base.run([
        "bash",
        "-lc",
        "git diff --cached --name-only -z | xargs -0 rg -n -i '\\b(password|imsi|imei|iccid|uicc|serial-number|software-id)\\b|private key' || true",
    ], timeout=30)
    return [
        line for line in scan.stdout.splitlines()
        if not line.startswith("tools/mixed_lte6_thick_pigtails_pre_firmware.py:")
    ]


class Runner(quick.Runner):
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
            "physical_change": "Both modems use thicker beige pigtails; previous thin black pigtails removed.",
            "thin_reference_campaign": THIN_BASELINE_ID,
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
            "p4_triggered": None,
            "items": {x["id"]: {"state": "PENDING", "attempts": 0, "history": []} for x in items()},
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

        if not routeros_ok or not routerboard_ok:
            self.progress["state"] = "BLOCKED_ROUTEROS_MISMATCH"
        elif not lte1_fw_ok or not lte2_fw_ok:
            self.progress["state"] = "BLOCKED_FIRMWARE_MISMATCH"
        elif not lte1_ok or not lte2_ok:
            self.progress["state"] = "BLOCKED_TOPOLOGY_MISMATCH"
        else:
            return True
        self.last_error = (
            f"{self.progress['state']}: routeros_ok={routeros_ok} routerboard_ok={routerboard_ok} "
            f"lte1={self.progress['modem_lte1']} lte2={self.progress['modem_lte2']}"
        )
        self.save_progress()
        self.update_matrix_summary()
        return False

    def write_manifest(self) -> None:
        lines = [
            f"# Manifest {CAMPAIGN_ID}",
            "",
            f"- Thin reference campaign: `{THIN_BASELINE_ID}`",
            "- Physical change: both LTE modems now use thicker beige pigtails; previous thin black pigtails removed.",
            "- Modem mapping: `lte1` = R11e-LTE6, `lte2` = FG621-EA.",
            "- Firmware upgrades: none performed by this campaign.",
            "- Only temporary RouterOS setting changed by the runner: `/interface lte ... band=`.",
        ]
        (PUBLIC / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
                for key in ("rssi_median", "rsrp_median", "rsrq_median", "sinr_median", "cqi_median", "ri_median", "rsrp_min", "rsrp_max", "sinr_min", "sinr_max", "cell_changes", "tx-queue-drop_delta"):
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

    def comparison_rows(self) -> list[tuple[str, str, str, dict[str, Any], dict[str, Any]]]:
        rows: list[tuple[str, str, str, dict[str, Any], dict[str, Any]]] = []
        for key in [("P1", "lte1"), ("P1", "lte2"), ("P2", "lte1"), ("P2", "lte2"), ("P3", "lte2")]:
            thin = THIN_REFERENCES.get(key, {})
            thick_summary = item_summary(key[0])
            thick = {
                "mbps": metric(thick_summary, key[1], "mbps"),
                "loss": metric(thick_summary, key[1], "loss"),
                "p95": metric(thick_summary, key[1], "p95"),
                "rsrp": metric(thick_summary, key[1], "rsrp_median"),
                "sinr": metric(thick_summary, key[1], "sinr_median"),
            }
            if key[0] == "P3" and thick["mbps"] is None and item_map()["P3"]:
                state = self.progress["items"].get("P3", {}).get("state")
                if state == "SKIPPED_BAND_UNAVAILABLE":
                    continue
            rows.append((key[0], thin.get("modem", key[1]), thin.get("band", ""), thin, thick))
        return rows

    def recommendation(self) -> str:
        if not all(
            self.progress["items"].get(item_id, {}).get("state") in base.TERMINAL_ITEM_STATES
            for item_id in ("P1", "P2", "P3", "P4")
        ):
            return "PENDING_TERMINAL_RESULTS"
        p1 = item_summary("P1")
        p2 = item_summary("P2")
        r11e_loss = metric(p1, "lte1", "loss")
        r11e_mbps = metric(p1, "lte1", "mbps")
        fg_b3_loss = metric(p1, "lte2", "loss")
        fg_b3_mbps = metric(p1, "lte2", "mbps")
        fg_b3_p95 = metric(p1, "lte2", "p95")
        fg_b8_loss = metric(p2, "lte2", "loss")
        if (
            fg_b3_loss is not None
            and fg_b3_mbps is not None
            and fg_b3_p95 is not None
            and (fg_b3_loss < 3 or (fg_b3_mbps > 5.8 and fg_b3_p95 < 80))
        ):
            return "EXTEND_PIGTAIL_TESTING_BEFORE_FIRMWARE"
        if r11e_loss is not None and (r11e_loss > 2 or (r11e_mbps is not None and r11e_mbps < 5.8)):
            return "STOP_AND_VALIDATE_RF_HARDWARE"
        if fg_b8_loss is not None and fg_b8_loss > 2:
            return "STOP_AND_VALIDATE_RF_HARDWARE"
        return "PROCEED_TO_FG621_FIRMWARE_TEST"

    def write_report(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# Thick-pigtail validation {CAMPAIGN_ID}",
            "",
            f"Updated: {summary_obj['updated_at']}",
            "",
            f"Thin-pigtail reference: `{THIN_BASELINE_ID}`.",
            "Physical change: both modems now use thicker beige pigtails.",
            f"FG621 firmware verified before tests: `{self.progress.get('modem_lte2', {}).get('firmware') or EXPECTED_LTE2_FIRMWARE}`.",
            f"RouterOS verified before tests: `{self.progress.get('routeros') or TARGET_VERSION}`.",
            "",
            "| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for item_id, row in summary_obj["items"].items():
            for path_name, modem in (("lte1", EXPECTED_LTE1_MODEL), ("lte2", EXPECTED_LTE2_MODEL)):
                if item_id == "P4" and path_name == "lte1":
                    continue
                lines.append(
                    f"| {item_id} | {modem} | {row.get(f'{path_name}_band') or ''} | "
                    f"{compact(row.get(f'{path_name}_mbps'))} | {compact(row.get(f'{path_name}_loss_percent'))} | "
                    f"{compact(row.get(f'{path_name}_ping_p95_ms'))} | {compact(row.get(f'{path_name}_rsrp_median'))} | "
                    f"{compact(row.get(f'{path_name}_sinr_median'))} | {row.get('dual_status') or row.get('registration') or row.get('state') or ''} |"
                )
        lines += [
            "",
            "## Thin vs Thick",
            "",
            "| Modem | Band | Thin Mbps | Thick Mbps | Thin loss % | Thick loss % | Thin p95 | Thick p95 | Thin RSRP | Thick RSRP | Thin SINR | Thick SINR |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for _test, modem, band, thin, thick in self.comparison_rows():
            lines.append(
                f"| {modem} | {band} | {compact(thin.get('mbps'))} | {compact(thick.get('mbps'))} | "
                f"{compact(thin.get('loss'))} | {compact(thick.get('loss'))} | {compact(thin.get('p95'))} | {compact(thick.get('p95'))} | "
                f"{compact(thin.get('rsrp'))} | {compact(thick.get('rsrp'))} | {compact(thin.get('sinr'))} | {compact(thick.get('sinr'))} |"
            )
        rec = self.recommendation()
        p1_fg_loss = metric(item_summary("P1"), "lte2", "loss")
        p1_fg_p95 = metric(item_summary("P1"), "lte2", "p95")
        p2_fg_loss = metric(item_summary("P2"), "lte2", "loss")
        interpretation = "Pending terminal results."
        if rec == "PROCEED_TO_FG621_FIRMWARE_TEST":
            interpretation = "New thicker pigtails did not materially solve the FG621 B3 problem; B8 remains the clean comparison path."
        elif rec == "EXTEND_PIGTAIL_TESTING_BEFORE_FIRMWARE":
            interpretation = "FG621 B3 improved enough to justify longer pigtail validation before firmware work."
        elif rec == "STOP_AND_VALIDATE_RF_HARDWARE":
            interpretation = "Results suggest the physical RF installation needs validation before firmware work."
        lines += [
            "",
            "## Interpretation",
            "",
            f"- P1 FG621 B3 loss/p95: {compact(p1_fg_loss)}% / {compact(p1_fg_p95)} ms.",
            f"- P2 FG621 B8 loss: {compact(p2_fg_loss)}%.",
            f"- P4 triggered: `{str(bool(self.progress.get('p4_triggered'))).lower()}`.",
            f"- Original bands restored: `{str(bool(self.progress.get('bands_restored'))).lower()}`.",
            f"- {interpretation}",
            "",
            f"Final recommendation: `{rec}`",
        ]
        (PUBLIC / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_status(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# Status {CAMPAIGN_ID}",
            "",
            f"- State: {self.progress.get('state')}",
            f"- Current item: {self.progress.get('current_item') or '-'}",
            f"- Progress: {self.progress.get('completed_count')}/{self.progress.get('mandatory_total')}",
            f"- Bands restored: {self.progress.get('bands_restored')}",
            f"- P4 triggered: {self.progress.get('p4_triggered')}",
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
            "tools/mixed_lte6_thick_pigtails_pre_firmware.py",
            "tools/ltap_thick_pigtails_watchdog.py",
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

    def should_trigger_p4(self) -> bool:
        p1 = item_summary("P1")
        fg_loss = metric(p1, "lte2", "loss")
        fg_mbps = metric(p1, "lte2", "mbps")
        fg_p95 = metric(p1, "lte2", "p95")
        triggered = bool(
            fg_loss is not None
            and fg_mbps is not None
            and fg_p95 is not None
            and (fg_loss < 3 or (fg_mbps > 5.8 and fg_p95 < 80))
        )
        self.progress["p4_triggered"] = triggered
        self.save_progress()
        return triggered

    def run(self) -> None:
        self.start_heartbeat()
        try:
            if not self.verify_baseline():
                self.git_checkpoint("thick-pigtails: blocked baseline")
                return
            if not self.verify_lab_routes():
                self.wait_until("WAIT_NETWORK", self.verify_lab_routes, 120)
            self.save_original_bands()
            if not self.server_probe():
                self.wait_until("WAIT_SERVER", self.server_probe, 600)
            self.progress["state"] = "RUNNING"
            self.save_progress()
            self.update_matrix_summary()
            self.git_checkpoint("thick-pigtails: initialize")
            for item in items():
                state = self.progress["items"][item["id"]].get("state")
                if state in base.TERMINAL_ITEM_STATES:
                    continue
                if STOP_FILE.exists():
                    break
                if item["id"] == "P4" and not self.should_trigger_p4():
                    self.transition("P4", "SKIPPED_NOT_TRIGGERED", attempts=0, registration="P4_NOT_TRIGGERED")
                    self.update_matrix_summary()
                    self.git_checkpoint("thick-pigtails: skip P4")
                    continue
                self.run_item(item)
            if STOP_FILE.exists() or all(x.get("state") in base.TERMINAL_ITEM_STATES for x in self.progress["items"].values()):
                self.restore_until_verified()
                self.final_monitor_snapshots()
                self.update_matrix_summary()
                self.git_checkpoint("thick-pigtails: finalize")
        finally:
            self.close()

    def final_monitor_snapshots(self) -> None:
        final_dir = RUNTIME / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        base.atomic_write_json(final_dir / "lte1_monitor.json", self.monitor("lte1"))
        base.atomic_write_json(final_dir / "lte2_monitor.json", self.monitor("lte2"))
        self.progress["final_monitor_snapshots_recorded_at"] = utcnow()
        self.save_progress()

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
                registration_status = "B7_UNAVAILABLE_THICK_PIGTAIL" if item_id == "P3" else "band did not register/verify"
                self.transition(item_id, "SKIPPED_BAND_UNAVAILABLE", attempts=attempts, bands=bands, registration=registration_status, monitor=base.sanitize_obj(registration))
                self.update_matrix_summary()
                self.git_checkpoint(f"thick-pigtails: {item_id} unavailable")
                return

            self.transition(item_id, "READY", registration="REGISTERED", monitor=base.sanitize_obj(registration))
            max_attempts = 1 if item_id == "P4" else 2
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
                    terminal_status = data.get("dual_status")
                    self.transition(item_id, "COMPLETE", attempts=attempts, dual_status=terminal_status, registration="REGISTERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"thick-pigtails: complete {item_id}")
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
                    self.git_checkpoint(f"thick-pigtails: failed {item_id}")
                    return
        except Exception as exc:
            self.last_error = repr(exc)
            attempts += 1
            max_attempts = 1 if item_id == "P4" else 2
            terminal = "FAILED_AFTER_RETRIES" if attempts >= max_attempts else "RETRY_PENDING"
            self.transition(item_id, terminal, attempts=attempts, last_error=self.last_error)
            self.update_matrix_summary()
            self.git_checkpoint(f"thick-pigtails: {terminal.lower()} {item_id}")


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
