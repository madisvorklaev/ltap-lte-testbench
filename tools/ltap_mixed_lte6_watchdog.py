#!/usr/bin/env python3
"""External watchdog for the mixed LTE6 campaign systemd service."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
CAMPAIGN_ID = "mixed-lte6-matrix-7.24rc3"
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
HEARTBEAT = RUNTIME / "HEARTBEAT.json"
LOG = RUNTIME / "watchdog.log"
SERVICE = "ltap-mixed-lte6-matrix.service"


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def append_log(message: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    stamp = now().isoformat(timespec="seconds")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {message}\n")


def load_heartbeat() -> dict[str, Any] | None:
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:
        return None


def restart(reason: str) -> int:
    append_log(f"restart {SERVICE}: {reason}")
    cp = subprocess.run(
        ["systemctl", "--user", "restart", SERVICE],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if cp.returncode != 0:
        append_log(f"restart failed rc={cp.returncode}: {cp.stderr.strip()}")
    return cp.returncode


def max_legitimate_stall_s(hb: dict[str, Any]) -> int:
    item_state = hb.get("item_state")
    elapsed = int(hb.get("item_elapsed_s") or 0)
    if item_state == "RUNNING":
        # Long stability runs are 600 s; allow warmup/cooldown and a recovery margin.
        if elapsed <= 750:
            return 900
        return 300
    if str(hb.get("campaign_state", "")).startswith("WAIT_"):
        return 1800
    if hb.get("campaign_state") in {"BLOCKED_TOPOLOGY_MISMATCH", "BLOCKED_VERSION_MISMATCH", "RESTORE_RETRY"}:
        return 1800
    return 420


def main() -> int:
    hb = load_heartbeat()
    if not hb:
        if HEARTBEAT.exists():
            return restart("heartbeat unreadable")
        append_log("no heartbeat yet")
        return 0

    hb_time = parse_time(hb.get("timestamp"))
    if hb_time is None:
        return restart("heartbeat timestamp missing/unparseable")

    age = (now() - hb_time).total_seconds()
    if age > 180:
        return restart(f"heartbeat stale age_s={age:.0f}")

    progress_time = parse_time(hb.get("worker_last_progress_at"))
    if progress_time is None:
        return restart("worker_last_progress_at missing/unparseable")

    stall = (now() - progress_time).total_seconds()
    limit = max_legitimate_stall_s(hb)
    if stall > limit:
        return restart(f"worker progress stale stall_s={stall:.0f} limit_s={limit}")

    append_log(
        "ok "
        f"state={hb.get('campaign_state')} item={hb.get('current_item')} "
        f"item_state={hb.get('item_state')} hb_age_s={age:.0f} worker_stall_s={stall:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
