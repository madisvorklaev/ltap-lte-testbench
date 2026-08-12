#!/usr/bin/env python3
"""Verify ELMO LTE drive-test v2 parsers and collected session artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ltap_testbench.drive_tests.v2 import analyze_session, synthetic_verification, write_verification_report


def iperf_capabilities() -> dict[str, object]:
    out: dict[str, object] = {"available": shutil.which("iperf3") is not None}
    if not out["available"]:
        return out
    cp = subprocess.run(["iperf3", "--version"], text=True, capture_output=True, timeout=5)
    first = (cp.stdout or cp.stderr).splitlines()[0] if (cp.stdout or cp.stderr).splitlines() else "unknown"
    out["version"] = first
    hp = subprocess.run(["iperf3", "--help"], text=True, capture_output=True, timeout=5)
    help_text = hp.stdout + hp.stderr
    out["json_stream_supported"] = "--json-stream" in help_text
    out["forceflush_supported"] = "--forceflush" in help_text
    return out


def has_partial_stop(runtime: Path) -> bool:
    for name in ("traffic_lte1.jsonl", "traffic_lte2.jsonl"):
        path = runtime / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("partial_reason") == "PARTIAL_STOPPED_BY_USER":
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", help="Optional live validation session to analyze")
    ap.add_argument("--legacy-session-id", default="drive-20260811-213442-seedri-smarten-seedri")
    ap.add_argument("--output", default="DRIVE_SKILL_V2_VERIFICATION.md")
    args = ap.parse_args()

    checks = synthetic_verification()
    live = {"iperf3": iperf_capabilities(), "critical_pass": False}
    legacy_runtime = REPO / "runtime/drive-tests" / args.legacy_session_id
    legacy_public = REPO / "results-public/drive-tests" / args.legacy_session_id
    if legacy_runtime.exists() and legacy_public.exists():
        legacy_summary = analyze_session(legacy_runtime, legacy_public)
        live["legacy_regression"] = legacy_summary
        checks.append(
            type(checks[0])(
                "Regression analyzer labels first drive as legacy/coarse",
                legacy_summary.get("resolution") == "LEGACY_COARSE_EPOCH_DATA",
                json.dumps(legacy_summary),
            )
        )
    else:
        checks.append(type(checks[0])("Regression fixture exists", False, str(legacy_runtime)))

    if args.session_id:
        runtime = REPO / "runtime/drive-tests" / args.session_id
        public = REPO / "results-public/drive-tests" / args.session_id
        summary = analyze_session(runtime, public)
        partial_stop = has_partial_stop(runtime)
        live["session_summary"] = summary
        live["mid_epoch_stop_preserved"] = partial_stop
        live["critical_pass"] = bool(
            summary.get("gps_valid_fixes", 0) > 0
            and summary.get("lte1_samples", 0) >= 150
            and summary.get("lte2_samples", 0) >= 150
            and summary.get("ping_lte1_samples", 0) > 0
            and summary.get("ping_lte2_samples", 0) > 0
            and (summary.get("traffic_loss_resolution_s") or 999) <= 15
            and summary.get("timeline_rows", 0) > 0
            and partial_stop
        )
        if not live["critical_pass"]:
            live["blocker"] = "FAIL_STOP_PRESERVATION" if not partial_stop else "FAIL_DRIVE_SKILL_V2"
    else:
        live["blocker"] = "FAIL_DRIVE_SKILL_V2"
        live["note"] = "Live stationary validation session was not supplied."

    classification = write_verification_report(REPO / args.output, checks, live)
    print(classification)
    return 0 if classification == "PASS_DRIVE_SKILL_V2" else 1


if __name__ == "__main__":
    raise SystemExit(main())
