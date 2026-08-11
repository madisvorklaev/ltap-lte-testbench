#!/usr/bin/env python3
"""Elisa/Telia SIM crossover campaign for R11e-LTE6 and FG621-EA."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import fg621_pre_firmware_quick_baseline as quick


base = quick.base
CAMPAIGN_ID = "elisa-telia-crossover-fg621-lte6"
BRANCH = "elisa-telia-crossover-fg621-lte6"
TARGET_VERSION = "7.24rc3"
EXPECTED_LTE1_MODEL = "R11e-LTE6"
EXPECTED_LTE1_FIRMWARE = "R11e-LTE6_V034"
EXPECTED_LTE2_MODEL = "FG621-EA"
EXPECTED_LTE2_FIRMWARE = "16121.1034.00.01.01.10"

REPO = base.REPO
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
PUBLIC = REPO / "results-public" / CAMPAIGN_ID
STOP_FILE = REPO / "runtime/STOP_ELISA_TELIA_CROSSOVER_FG621_LTE6"

base.CAMPAIGN_ID = CAMPAIGN_ID
base.RUNTIME = RUNTIME
base.PUBLIC = PUBLIC
base.STOP_FILE = STOP_FILE
base.BRANCH = BRANCH
base.TARGET_VERSION = TARGET_VERSION
base.TERMINAL_ITEM_STATES = set(base.TERMINAL_ITEM_STATES) | {"SKIPPED_NOT_AVAILABLE"}

quick.CAMPAIGN_ID = CAMPAIGN_ID
quick.BRANCH = BRANCH
quick.RUNTIME = RUNTIME
quick.PUBLIC = PUBLIC
quick.STOP_FILE = STOP_FILE

CANDIDATE_BANDS = ["1", "3", "7", "8", "20", "38"]
SELECTION_PRIORITY = ["3", "8", "7", "20", "1"]
OPERATOR_ALIASES = {
    "elisa": "elisa",
    "elisa eesti": "elisa",
    "telia": "telia",
    "telia ee": "telia",
    "telia eesti": "telia",
    "emt": "telia",
}


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def compact(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def normalize_operator(value: str | None) -> str | None:
    raw = (value or "").strip().lower()
    raw = re.sub(r"\s+", " ", raw)
    if raw in OPERATOR_ALIASES:
        return OPERATOR_ALIASES[raw]
    if "elisa" in raw:
        return "elisa"
    if "telia" in raw or "emt" in raw:
        return "telia"
    return raw or None


def sim_id_from(identity: dict[str, Any]) -> str:
    source = identity.get("iccid") or identity.get("uicc") or identity.get("imsi") or identity.get("subscriber-number")
    if not source:
        source = f"{identity.get('interface')}:{identity.get('operator')}:{identity.get('modem')}"
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
    return f"SIM-{digest}"


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def metric(summary: dict[str, Any], path_name: str, name: str) -> Any:
    ps = summary.get(path_name) or {}
    if name == "mbps":
        return (ps.get("iperf") or {}).get("mbps")
    if name == "loss":
        return (ps.get("iperf") or {}).get("lost_percent")
    if name == "p95":
        return (ps.get("ping") or {}).get("p95_ms")
    radio = ps.get("radio_target") or {}
    tele = ps.get("telemetry_medians") or {}
    return tele.get(name) if name in tele else radio.get(name)


def item_id(phase: str, band: str) -> str:
    return f"{phase}-B{band}" if band else f"{phase}-AUTO"


def current_items(progress: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    selected = []
    if progress:
        selected = progress.get("selected_bands") or []
        if progress.get("auto_fallback_selected"):
            selected = [""]
    out: list[dict[str, Any]] = []
    for phase in ("A", "B"):
        for band in selected:
            out.append({
                "id": item_id(phase, band),
                "phase": f"PHASE_{phase}_LOADED",
                "crossover_phase": phase,
                "mode": "dual",
                "lte1_band": band,
                "lte2_band": band,
                "lte1_bitrate": "6M",
                "lte2_bitrate": "6M",
                "duration": 300,
                "packet_length": 1200,
                "required": True,
            })
    return out


def items() -> list[dict[str, Any]]:
    progress = base.load_json(RUNTIME / "PROGRESS.json", {})
    return current_items(progress)


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
        "git diff --cached --name-only -z | xargs -0 rg -n -i '\\b(password|imsi|imei|iccid|uicc|subscriber-number|serial-number|software-id)\\b|private key' || true",
    ], timeout=30)
    return [
        line for line in scan.stdout.splitlines()
        if not line.startswith("tools/elisa_telia_crossover_fg621_lte6.py:")
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
            "original_band_lte1": None,
            "original_band_lte2": None,
            "server_hostname": self.campaign.get("server_hostname"),
            "server_ipv4": self.campaign.get("server_ipv4"),
            "selected_bands": [],
            "auto_fallback_selected": False,
            "phase": "STARTUP",
            "phase_a_sim_map": None,
            "phase_b_sim_map": None,
            "sim_swap_verified": False,
            "completed_count": 0,
            "mandatory_total": 0,
            "current_item": None,
            "retry_queue": [],
            "push_pending": False,
            "bands_restored": False,
            "items": {},
            "last_pushed_commit": None,
            "worker_progress_counter": 0,
            "worker_last_progress_at": now_s,
        }
        self.save_progress(progress)
        return progress

    def save_progress(self, progress: dict[str, Any] | None = None) -> None:
        if progress is not None:
            self.progress = progress
        for item in current_items(self.progress):
            self.progress.setdefault("items", {}).setdefault(item["id"], {"state": "PENDING", "attempts": 0, "history": []})
        self.progress["mandatory_total"] = len(self.progress.get("items", {}))
        super().save_progress()

    def transition(self, item_id_: str, state: str, **fields: Any) -> None:
        item = self.progress.setdefault("items", {}).setdefault(item_id_, {"state": "PENDING", "attempts": 0, "history": []})
        item.update(fields)
        item["state"] = state
        item.setdefault("history", []).append({"at": utcnow(), "state": state, **fields})
        self.progress["current_item"] = item_id_
        plan = item_map().get(item_id_, {})
        self.progress["state"] = plan.get("phase") or self.progress.get("phase") or "RUNNING"
        self.current_state = state
        if state == "RUNNING":
            self.item_started_mono = time.monotonic()
        self.bump_worker_progress()
        self.save_progress()

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

    def at_chat(self, iface: str, command: str) -> str:
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        cp = self.router_call(f'/interface/lte/at-chat {iface} input="{escaped}"', timeout=12)
        return cp.stdout + ("\n" + cp.stderr if cp.stderr else "")

    def sim_identity(self, iface: str) -> dict[str, Any]:
        mon = self.monitor(iface)
        identity: dict[str, Any] = {
            "interface": iface,
            "modem": self.progress.get(f"modem_{iface}", {}).get("detected"),
            "operator": normalize_operator(mon.get("current-operator") or mon.get("operator")),
            "operator_raw": mon.get("current-operator") or mon.get("operator"),
            "apn": mon.get("apn"),
            "registration_state": mon.get("status"),
            "imsi": mon.get("imsi"),
            "iccid": mon.get("iccid"),
            "uicc": mon.get("uicc"),
            "subscriber-number": mon.get("subscriber-number"),
            "monitor": mon,
            "collected_at": utcnow(),
        }
        if not (identity.get("iccid") or identity.get("uicc")):
            raw = self.at_chat(iface, "AT+QCCID")
            m = re.search(r"QCCID:\s*([0-9A-Fa-f]+)", raw)
            if m:
                identity["iccid"] = m.group(1)
                identity["iccid_source"] = "AT+QCCID"
        if not identity.get("imsi"):
            raw = self.at_chat(iface, "AT+CIMI")
            m = re.search(r"\b([0-9]{12,18})\b", raw)
            if m:
                identity["imsi"] = m.group(1)
                identity["imsi_source"] = "AT+CIMI"
        identity["sim_id"] = sim_id_from(identity)
        return identity

    def public_sim_entry(self, identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "interface": identity.get("interface"),
            "modem": identity.get("modem"),
            "operator": identity.get("operator"),
            "operator_raw": identity.get("operator_raw"),
            "sim_id": identity.get("sim_id"),
            "registration_state": identity.get("registration_state"),
            "apn_present": bool(identity.get("apn")),
        }

    def collect_sim_map(self, phase_name: str) -> dict[str, Any]:
        local = {
            "phase": phase_name,
            "collected_at": utcnow(),
            "interfaces": {
                "lte1": self.sim_identity("lte1"),
                "lte2": self.sim_identity("lte2"),
            },
        }
        base.atomic_write_json(RUNTIME / f"SIM_MAP_LOCAL_{phase_name}.json", local)
        if phase_name == "PHASE_A":
            base.atomic_write_json(RUNTIME / "SIM_MAP_LOCAL.json", local)
        public = {
            "phase": phase_name,
            "collected_at": local["collected_at"],
            "interfaces": {
                iface: self.public_sim_entry(value)
                for iface, value in local["interfaces"].items()
            },
        }
        base.atomic_write_json(PUBLIC / ("SIM_MAP_PUBLIC.json" if phase_name == "PHASE_A" else f"SIM_MAP_PUBLIC_{phase_name}.json"), public)
        return public

    def validate_one_elisa_one_telia(self, sim_map: dict[str, Any]) -> bool:
        operators = [entry.get("operator") for entry in sim_map.get("interfaces", {}).values()]
        if sorted(operators) == ["elisa", "telia"]:
            return True
        self.progress["state"] = "BLOCKED_OPERATOR_MAPPING"
        self.last_error = f"Expected one Elisa and one Telia SIM, detected {operators}"
        self.save_progress()
        self.update_matrix_summary()
        return False

    def operator_iface(self, sim_map: dict[str, Any], operator: str) -> str | None:
        for iface, entry in sim_map.get("interfaces", {}).items():
            if entry.get("operator") == operator:
                return iface
        return None

    def radio_snapshot(self, iface: str) -> dict[str, Any]:
        mon = self.monitor(iface)
        keys = ("status", "current-operator", "primary-band", "earfcn", "enb-id", "sector-id", "cell-id", "phy-cellid", "rsrp", "rsrq", "sinr", "cqi", "ri", "ca-band")
        return {key: mon.get(key) for key in keys if key in mon}

    def discover_band(self, iface: str, band: str) -> dict[str, Any]:
        result: dict[str, Any] = {"interface": iface, "band": f"B{band}", "started_at": utcnow()}
        try:
            self.set_band(iface, band)
        except Exception as exc:
            result.update({"status": "UNSUPPORTED_BY_MODEM", "error": repr(exc), "finished_at": utcnow()})
            return result
        deadline = time.time() + 60
        last: dict[str, Any] = {}
        while time.time() < deadline:
            mon = self.monitor(iface)
            last = mon
            if str(mon.get("status", "")).lower() in base.REGISTERED_LTE_STATES and self.primary_band_allowed(mon.get("primary-band", ""), band):
                result.update({"status": "AVAILABLE", "snapshot": self.radio_snapshot(iface), "finished_at": utcnow()})
                return result
            time.sleep(5)
        result.update({"status": "REGISTRATION_TIMEOUT", "last_monitor": base.sanitize_obj(last), "finished_at": utcnow()})
        return result

    def run_discovery(self) -> None:
        if self.progress.get("telia_band_discovery"):
            return
        sim_map = self.progress.get("phase_a_sim_map") or self.collect_sim_map("PHASE_A")
        self.progress["phase_a_sim_map"] = sim_map
        self.save_progress()
        if not self.validate_one_elisa_one_telia(sim_map):
            return
        telia_iface = self.operator_iface(sim_map, "telia")
        elisa_iface = self.operator_iface(sim_map, "elisa")
        if not telia_iface or not elisa_iface:
            self.progress["state"] = "BLOCKED_OPERATOR_MAPPING"
            self.save_progress()
            return
        candidates = list(CANDIDATE_BANDS)
        if telia_iface == "lte2" and "28" not in candidates:
            candidates.append("28")
        self.progress["state"] = "TELIA_BAND_DISCOVERY"
        self.save_progress()
        telia: dict[str, Any] = {
            "telia_interface": telia_iface,
            "operator": "telia",
            "started_at": utcnow(),
            "bands": {},
        }
        for band in candidates:
            telia["bands"][f"B{band}"] = self.discover_band(telia_iface, band)
            base.atomic_write_json(PUBLIC / "TELIA_BAND_DISCOVERY.json", base.sanitize_obj(telia))
            self.bump_worker_progress()
            self.save_progress()
        telia["finished_at"] = utcnow()
        base.atomic_write_json(PUBLIC / "TELIA_BAND_DISCOVERY.json", base.sanitize_obj(telia))
        self.progress["telia_band_discovery"] = telia
        self.save_progress()

        common: dict[str, Any] = {"elisa_interface": elisa_iface, "telia_interface": telia_iface, "bands": {}, "updated_at": utcnow()}
        self.progress["state"] = "ELISA_OVERLAP_DISCOVERY"
        self.save_progress()
        for band_key, result in telia["bands"].items():
            band = band_key.removeprefix("B")
            if result.get("status") != "AVAILABLE" or band == "28":
                common["bands"][band_key] = {"telia": result.get("status") == "AVAILABLE", "elisa": False, "selected": False, "reason": "Telia unavailable or informational-only band"}
                continue
            elisa_result = self.discover_band(elisa_iface, band)
            common["bands"][band_key] = {
                "telia": True,
                "elisa": elisa_result.get("status") == "AVAILABLE",
                "selected": False,
                "reason": "",
                "elisa_result": elisa_result,
            }
            base.atomic_write_json(PUBLIC / "COMMON_BANDS.json", base.sanitize_obj(common))
            self.bump_worker_progress()
            self.save_progress()
        selected: list[str] = []
        for band in SELECTION_PRIORITY:
            entry = common["bands"].get(f"B{band}")
            if entry and entry.get("telia") and entry.get("elisa") and len(selected) < 3:
                selected.append(band)
                entry["selected"] = True
                entry["reason"] = "selected by priority algorithm"
        if not selected:
            self.progress["auto_fallback_selected"] = True
            common["auto_fallback"] = "No exact useful matching bands selected; run AUTO/AUTO exploratory behavior if registration permits."
        self.progress["selected_bands"] = selected
        self.progress["common_bands"] = common
        self.progress["items"] = {x["id"]: {"state": "PENDING", "attempts": 0, "history": []} for x in current_items(self.progress)}
        self.save_progress()
        base.atomic_write_json(PUBLIC / "COMMON_BANDS.json", base.sanitize_obj(common))
        self.update_matrix_summary()
        self.git_checkpoint("crossover: discovery complete")

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
                for key in values:
                    value = mon.get(key)
                    if isinstance(value, str):
                        match = re.search(r"-?\d+(?:\.\d+)?", value)
                        value = float(match.group(0)) if match else None
                    if isinstance(value, (int, float)):
                        values[key].append(float(value))
        return {f"{key}_median": median(series) for key, series in values.items() if series}

    def publish_run(self, item_id_: str, data: dict[str, Any]) -> None:
        sim_map = self.progress.get("phase_a_sim_map") if item_id_.startswith("A-") else self.progress.get("phase_b_sim_map")
        for path_name in ("lte1", "lte2"):
            if data.get(path_name):
                data[path_name]["operator_context"] = (sim_map or {}).get("interfaces", {}).get(path_name, {})
        super().publish_run(item_id_, data)
        run_dir = PUBLIC / "runs" / item_id_
        summary = base.load_json(run_dir / "summary.json", {})
        for path_name in ("lte1", "lte2"):
            if summary.get(path_name):
                summary[path_name]["telemetry_medians"] = self.collect_telemetry_medians(run_dir, path_name)
        base.atomic_write_json(run_dir / "summary.json", base.sanitize_obj(summary))
        self.update_matrix_summary()

    def run_loaded_item(self, item: dict[str, Any]) -> None:
        item_id_ = item["id"]
        attempts = int(self.progress["items"][item_id_].get("attempts", 0))
        try:
            self.transition(item_id_, "APPLYING_BANDS", attempts=attempts)
            for iface, band in self.desired_bands(item).items():
                if band is not None:
                    self.set_band(iface, band)
            time.sleep(5)
            bands = self.read_band_values()
            if not all((bands[iface] or "") == (band or "") for iface, band in self.desired_bands(item).items() if band is not None):
                raise RuntimeError(f"band readback mismatch: {bands}")
            self.transition(item_id_, "WAITING_REGISTRATION", attempts=attempts, bands=bands)
            verified, registration = self.wait_registered_for_item(item, 120)
            if not verified:
                self.transition(item_id_, "SKIPPED_NOT_AVAILABLE", attempts=attempts, registration="BAND_NOT_AVAILABLE", monitor=base.sanitize_obj(registration))
                self.update_matrix_summary()
                self.git_checkpoint(f"crossover: {item_id_} unavailable")
                return
            self.transition(item_id_, "READY", attempts=attempts, registration="REGISTERED", monitor=base.sanitize_obj(registration))
            while attempts < 2:
                if STOP_FILE.exists():
                    return
                attempts += 1
                self.transition(item_id_, "RUNNING", attempts=attempts)
                ok, data = self.run_dual(item, attempts)
                data["registration"] = "REGISTERED"
                data["registration_monitor"] = base.sanitize_obj(registration)
                self.transition(item_id_, "ANALYZING", attempts=attempts, dual_status=data.get("dual_status"))
                self.transition(item_id_, "SANITIZING", attempts=attempts)
                self.publish_run(item_id_, data)
                if ok:
                    self.transition(item_id_, "COMPLETE", attempts=attempts, dual_status=data.get("dual_status"), registration="REGISTERED")
                    self.update_matrix_summary()
                    self.git_checkpoint(f"crossover: complete {item_id_}")
                    return
                self.last_error = data.get("dual_status") or "run failed"
                if attempts < 2:
                    self.transition(item_id_, "RETRY_PENDING", attempts=attempts, last_error=self.last_error)
                    for _ in range(60):
                        if STOP_FILE.exists():
                            return
                        time.sleep(1)
            self.transition(item_id_, "FAILED_AFTER_RETRIES", attempts=attempts, last_error=self.last_error, registration="REGISTERED")
            self.update_matrix_summary()
            self.git_checkpoint(f"crossover: failed {item_id_}")
        except Exception as exc:
            self.last_error = repr(exc)
            attempts += 1
            terminal = "FAILED_AFTER_RETRIES" if attempts >= 2 else "RETRY_PENDING"
            self.transition(item_id_, terminal, attempts=attempts, last_error=self.last_error)
            self.update_matrix_summary()
            self.git_checkpoint(f"crossover: {terminal.lower()} {item_id_}")

    def phase_items(self, phase: str) -> list[dict[str, Any]]:
        return [item for item in current_items(self.progress) if item["crossover_phase"] == phase]

    def wait_for_swap(self) -> bool:
        if self.progress.get("sim_swap_verified"):
            return True
        self.restore_until_verified()
        self.progress["state"] = "WAIT_PHYSICAL_SIM_SWAP"
        self.progress["phase"] = "WAIT_PHYSICAL_SIM_SWAP"
        self.progress["bands_restored"] = True
        self.save_progress()
        self.update_matrix_summary()
        self.git_checkpoint("crossover: waiting for physical sim swap")
        before = self.progress.get("phase_a_sim_map") or {}
        before_sims = {iface: entry.get("sim_id") for iface, entry in before.get("interfaces", {}).items()}
        while not STOP_FILE.exists():
            try:
                after = self.collect_sim_map("PHASE_B")
                after_sims = {iface: entry.get("sim_id") for iface, entry in after.get("interfaces", {}).items()}
                reversed_ok = before_sims.get("lte1") == after_sims.get("lte2") and before_sims.get("lte2") == after_sims.get("lte1")
                if reversed_ok and self.validate_one_elisa_one_telia(after):
                    self.progress["phase_b_sim_map"] = after
                    self.progress["sim_swap_verified"] = True
                    self.progress["bands_restored"] = False
                    self.progress["state"] = "PHASE_B_READY"
                    self.progress["phase"] = "PHASE_B_READY"
                    self.last_error = ""
                    self.save_progress()
                    self.update_matrix_summary()
                    self.git_checkpoint("crossover: sim swap verified")
                    return True
                self.last_error = f"Waiting for SIM swap: before={before_sims} after={after_sims}"
                self.save_progress()
            except Exception as exc:
                self.last_error = repr(exc)
                self.save_progress()
            time.sleep(60)
        return False

    def update_matrix_summary(self) -> None:
        rows: list[dict[str, Any]] = []
        summary_obj: dict[str, Any] = {"campaign_id": CAMPAIGN_ID, "updated_at": utcnow(), "items": {}, "selected_bands": self.progress.get("selected_bands", [])}
        for item in current_items(self.progress):
            state = self.progress.get("items", {}).get(item["id"], {})
            run_summary = base.load_json(PUBLIC / "runs" / item["id"] / "summary.json", {})
            row = {
                "item_id": item["id"],
                "phase": item["crossover_phase"],
                "state": state.get("state"),
                "attempts": state.get("attempts", 0),
                "band": item.get("lte1_band") or "AUTO",
                "dual_status": run_summary.get("dual_status"),
                "registration": state.get("registration") or run_summary.get("registration"),
            }
            for path_name in ("lte1", "lte2"):
                ps = run_summary.get(path_name) or {}
                op = (ps.get("operator_context") or {}).get("operator")
                row[f"{path_name}_operator"] = op
                row[f"{path_name}_sim_id"] = (ps.get("operator_context") or {}).get("sim_id")
                row[f"{path_name}_modem"] = self.progress.get(f"modem_{path_name}", {}).get("detected")
                row[f"{path_name}_mbps"] = metric(run_summary, path_name, "mbps")
                row[f"{path_name}_loss_percent"] = metric(run_summary, path_name, "loss")
                row[f"{path_name}_ping_p95_ms"] = metric(run_summary, path_name, "p95")
                row[f"{path_name}_rsrp_median"] = metric(run_summary, path_name, "rsrp_median")
                row[f"{path_name}_rsrq_median"] = metric(run_summary, path_name, "rsrq_median")
                row[f"{path_name}_sinr_median"] = metric(run_summary, path_name, "sinr_median")
            rows.append(row)
            summary_obj["items"][item["id"]] = row
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

    def write_manifest(self) -> None:
        lines = [
            f"# Manifest {CAMPAIGN_ID}",
            "",
            "- Purpose: Elisa/Telia SIM crossover across R11e-LTE6 and FG621-EA.",
            "- `lte1` = R11e-LTE6 / V034; `lte2` = FG621-EA / 16121.1034.00.01.01.10.",
            "- Thick beige pigtails, modem slots, antennas, RouterOS and routing remain unchanged.",
            "- Full SIM identifiers are local-only in runtime; public files use pseudonymous SIM IDs.",
            "- Only temporary RouterOS setting changed by the runner: `/interface lte ... band=`.",
        ]
        (PUBLIC / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def classification(self) -> str:
        if not self.progress.get("sim_swap_verified"):
            return "INCONCLUSIVE_OPERATOR_CROSSOVER"
        rows = base.load_json(PUBLIC / "matrix_summary.json", {}).get("items", {})
        b3: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows.values():
            if row.get("band") != "3":
                continue
            for path_name in ("lte1", "lte2"):
                modem = row.get(f"{path_name}_modem") or ""
                operator = row.get(f"{path_name}_operator")
                if operator:
                    b3[(modem, operator)] = {
                        "loss": row.get(f"{path_name}_loss_percent"),
                        "p95": row.get(f"{path_name}_ping_p95_ms"),
                        "mbps": row.get(f"{path_name}_mbps"),
                    }
        def poor(x: dict[str, Any] | None) -> bool:
            if not x:
                return False
            loss = x.get("loss")
            p95 = x.get("p95")
            mbps = x.get("mbps")
            return (loss is not None and loss > 5) or (p95 is not None and p95 > 100) or (mbps is not None and mbps < 5.6)
        def good(x: dict[str, Any] | None) -> bool:
            if not x:
                return False
            return (x.get("mbps") or 0) >= 5.8 and (x.get("loss") or 100) < 1 and (x.get("p95") or 999) < 60
        r_elisa = b3.get((EXPECTED_LTE1_MODEL, "elisa"))
        r_telia = b3.get((EXPECTED_LTE1_MODEL, "telia"))
        f_elisa = b3.get((EXPECTED_LTE2_MODEL, "elisa"))
        f_telia = b3.get((EXPECTED_LTE2_MODEL, "telia"))
        if poor(f_elisa) and poor(f_telia) and good(r_elisa) and good(r_telia):
            return "FG621_B3_MODEM_SPECIFIC"
        if poor(f_elisa) and good(f_telia) and good(r_elisa) and good(r_telia):
            return "FG621_ELISA_INTERACTION"
        if poor(r_elisa) and poor(f_elisa) and not poor(r_telia) and not poor(f_telia):
            return "ELISA_B3_RAN_OR_OPERATOR_EFFECT"
        if poor(r_telia) and poor(f_telia) and not poor(r_elisa) and not poor(f_elisa):
            return "TELIA_B3_RAN_OR_OPERATOR_EFFECT"
        return "INCONCLUSIVE_OPERATOR_CROSSOVER"

    def write_report(self, summary_obj: dict[str, Any]) -> None:
        phase_a = self.progress.get("phase_a_sim_map") or {}
        phase_b = self.progress.get("phase_b_sim_map") or {}
        lines = [
            f"# Elisa/Telia crossover {CAMPAIGN_ID}",
            "",
            f"Updated: {summary_obj['updated_at']}",
            "",
            f"RouterOS: `{self.progress.get('routeros') or TARGET_VERSION}`.",
            f"Bands restored: `{str(bool(self.progress.get('bands_restored'))).lower()}`.",
            f"SIM swap verified: `{str(bool(self.progress.get('sim_swap_verified'))).lower()}`.",
            "",
            "## SIM Map",
            "",
            f"- Phase A: `{json.dumps(phase_a.get('interfaces', {}), sort_keys=True)}`",
            f"- Phase B: `{json.dumps(phase_b.get('interfaces', {}), sort_keys=True)}`",
            "",
            "## Selected Bands",
            "",
            f"- Selected exact bands: `{', '.join('B'+b for b in self.progress.get('selected_bands', [])) or 'none'}`",
            f"- AUTO fallback: `{str(bool(self.progress.get('auto_fallback_selected'))).lower()}`",
            "",
            "| Item | Phase | Band | Status | LTE1 operator | LTE1 Mbps | LTE1 loss % | LTE1 p95 | LTE2 operator | LTE2 Mbps | LTE2 loss % | LTE2 p95 |",
            "|---|---|---|---|---|---:|---:|---:|---|---:|---:|---:|",
        ]
        for row in summary_obj["items"].values():
            lines.append(
                f"| {row.get('item_id')} | {row.get('phase')} | {row.get('band')} | {row.get('dual_status') or row.get('registration') or row.get('state') or ''} | "
                f"{row.get('lte1_operator') or ''} | {compact(row.get('lte1_mbps'))} | {compact(row.get('lte1_loss_percent'))} | {compact(row.get('lte1_ping_p95_ms'))} | "
                f"{row.get('lte2_operator') or ''} | {compact(row.get('lte2_mbps'))} | {compact(row.get('lte2_loss_percent'))} | {compact(row.get('lte2_ping_p95_ms'))} |"
            )
        lines += [
            "",
            "## Required Answers",
            "",
            "1. Which pseudonymous SIM was Elisa? See `SIM_MAP_PUBLIC.json` and Phase B map above.",
            "2. Which pseudonymous SIM was Telia? See `SIM_MAP_PUBLIC.json` and Phase B map above.",
            "3. Which modem initially contained each SIM? See Phase A map above.",
            f"4. Was the physical crossover verified correctly? `{str(bool(self.progress.get('sim_swap_verified'))).lower()}`.",
            "5. Which bands were available from Telia? See `TELIA_BAND_DISCOVERY.json`.",
            "6. Which bands were simultaneously comparable with Elisa? See `COMMON_BANDS.json`.",
            f"7. Was B3 available from both operators? `{str('3' in (self.progress.get('selected_bands') or [])).lower()}`.",
            "8. On B3, how did R11e perform with Elisa vs Telia? See matrix table.",
            "9. On B3, how did FG621 perform with Elisa vs Telia? See matrix table.",
            "10. Does the FG621 B3 problem follow the modem across operators? See final classification.",
            "11. Does it specifically follow Elisa? See final classification.",
            "12. Are operator differences explained by different EARFCN/bandwidth/cell parameters? See per-run radio summaries and discovery files.",
            "13. Which exact bands appear best for FG621 on Telia? See matrix table.",
            "14. Which exact bands appear best for R11e on Telia? See matrix table.",
            f"15. What happened under AUTO, if AUTO was used? AUTO fallback `{str(bool(self.progress.get('auto_fallback_selected'))).lower()}`.",
            "16. Is unrestricted AUTO selection justified for either modem/operator? Final answer pending complete crossover.",
            "17. What should the next experiment be? Pending complete crossover.",
            "",
            self.classification(),
        ]
        (PUBLIC / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_status(self, summary_obj: dict[str, Any]) -> None:
        lines = [
            f"# Status {CAMPAIGN_ID}",
            "",
            f"- State: {self.progress.get('state')}",
            f"- Phase: {self.progress.get('phase')}",
            f"- Current item: {self.progress.get('current_item') or '-'}",
            f"- Progress: {self.progress.get('completed_count')}/{self.progress.get('mandatory_total')}",
            f"- Selected bands: {', '.join('B'+b for b in self.progress.get('selected_bands', [])) or '-'}",
            f"- SIM swap verified: {self.progress.get('sim_swap_verified')}",
            f"- Bands restored: {self.progress.get('bands_restored')}",
            f"- Last error: {self.last_error or self.progress.get('last_error') or ''}",
            "",
            "| Item | State | Attempts | Status |",
            "| --- | --- | ---: | --- |",
        ]
        for item_id_, row in summary_obj["items"].items():
            lines.append(f"| {item_id_} | {row.get('state')} | {row.get('attempts')} | {row.get('dual_status') or row.get('registration') or ''} |")
        (PUBLIC / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def final_monitor_snapshots(self) -> None:
        final_dir = RUNTIME / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        base.atomic_write_json(final_dir / "lte1_monitor.json", self.monitor("lte1"))
        base.atomic_write_json(final_dir / "lte2_monitor.json", self.monitor("lte2"))
        self.progress["final_monitor_snapshots_recorded_at"] = utcnow()
        self.save_progress()

    def git_checkpoint(self, message: str) -> None:
        paths = [
            "tools/elisa_telia_crossover_fg621_lte6.py",
            "tools/ltap_elisa_telia_crossover_watchdog.py",
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

    def run_phase(self, phase: str) -> None:
        self.progress["phase"] = f"PHASE_{phase}"
        self.progress["state"] = f"PHASE_{phase}_LOADED"
        self.save_progress()
        for item in self.phase_items(phase):
            state = self.progress["items"][item["id"]].get("state")
            if state in base.TERMINAL_ITEM_STATES:
                continue
            if STOP_FILE.exists():
                return
            self.run_loaded_item(item)

    def run(self) -> None:
        self.start_heartbeat()
        try:
            if not self.verify_baseline():
                self.git_checkpoint("crossover: blocked baseline")
                return
            if not self.verify_lab_routes():
                self.wait_until("WAIT_NETWORK", self.verify_lab_routes, 120)
            self.save_original_bands()
            if not self.server_probe():
                self.wait_until("WAIT_SERVER", self.server_probe, 600)
            if not self.progress.get("phase_a_sim_map"):
                self.progress["state"] = "SIM_IDENTITY_VERIFICATION"
                self.progress["phase"] = "SIM_IDENTITY_VERIFICATION"
                self.progress["phase_a_sim_map"] = self.collect_sim_map("PHASE_A")
                self.save_progress()
                if not self.validate_one_elisa_one_telia(self.progress["phase_a_sim_map"]):
                    self.git_checkpoint("crossover: blocked sim mapping")
                    return
                self.update_matrix_summary()
                self.git_checkpoint("crossover: sim map verified")
            self.run_discovery()
            if not self.progress.get("selected_bands") and not self.progress.get("auto_fallback_selected"):
                self.progress["state"] = "BLOCKED_NO_COMMON_BANDS"
                self.save_progress()
                self.update_matrix_summary()
                self.git_checkpoint("crossover: no common bands")
                return
            if any(self.progress["items"][item["id"]].get("state") not in base.TERMINAL_ITEM_STATES for item in self.phase_items("A")):
                self.run_phase("A")
            if not self.wait_for_swap():
                return
            if any(self.progress["items"][item["id"]].get("state") not in base.TERMINAL_ITEM_STATES for item in self.phase_items("B")):
                self.run_phase("B")
            if all(x.get("state") in base.TERMINAL_ITEM_STATES for x in self.progress["items"].values()):
                self.restore_until_verified()
                self.final_monitor_snapshots()
                self.progress["state"] = "COMPLETE"
                self.progress["phase"] = "COMPLETE"
                self.save_progress()
                self.update_matrix_summary()
                self.git_checkpoint("crossover: finalize")
        finally:
            self.close()


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
