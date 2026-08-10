#!/usr/bin/env python3
"""Heartbeat watchdog logger for the Elisa/Telia crossover campaign."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
CAMPAIGN_ID = "elisa-telia-crossover-fg621-lte6"
RUNTIME = REPO / "runtime" / CAMPAIGN_ID
HEARTBEAT = RUNTIME / "HEARTBEAT.json"
LOG = RUNTIME / "watchdog.log"


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
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now().isoformat(timespec='seconds')} {message}\n")


def load_heartbeat() -> dict[str, Any] | None:
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:
        return None


def max_legitimate_stall_s(hb: dict[str, Any]) -> int:
    state = str(hb.get("campaign_state") or "")
    if state == "WAIT_PHYSICAL_SIM_SWAP":
        return 24 * 60 * 60
    if state.startswith("WAIT_"):
        return 1800
    if hb.get("item_state") == "RUNNING":
        return 900
    if state in {"TELIA_BAND_DISCOVERY", "ELISA_OVERLAP_DISCOVERY", "SIM_IDENTITY_VERIFICATION"}:
        return 900
    return 420


def main() -> int:
    hb = load_heartbeat()
    if not hb:
        append_log("no heartbeat yet")
        return 0
    hb_time = parse_time(hb.get("timestamp"))
    progress_time = parse_time(hb.get("worker_last_progress_at"))
    if hb_time is None or progress_time is None:
        append_log("bad heartbeat timestamp")
        return 2
    age = (now() - hb_time).total_seconds()
    stall = (now() - progress_time).total_seconds()
    limit = max_legitimate_stall_s(hb)
    if age > 180 or stall > limit:
        append_log(
            "stale "
            f"state={hb.get('campaign_state')} item={hb.get('current_item')} "
            f"item_state={hb.get('item_state')} hb_age_s={age:.0f} "
            f"worker_stall_s={stall:.0f} limit_s={limit}"
        )
        return 2
    append_log(
        "ok "
        f"state={hb.get('campaign_state')} item={hb.get('current_item')} "
        f"item_state={hb.get('item_state')} hb_age_s={age:.0f} worker_stall_s={stall:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
