---
name: "elmo-lte-drive-test"
description: "Start, monitor, mark, stop, verify, and analyze v2 ELMO dual-LTE moving drive tests."
---

# ELMO LTE Drive Test v2.0

Use this skill for variable-length moving-car LTE tests on Madis's ELMO/LtAP dual-LTE setup.

## Version

Every new session must record:

```json
{
  "skill": "elmo-lte-drive-test",
  "skill_version": "2.0"
}
```

## Maintained Implementation

- Worker CLI: `tools/elmo_lte_drive_worker.py`
- Parser/analyzer module: `src/ltap_testbench/drive_tests/v2.py`
- Verification CLI: `tools/verify_drive_skill_v2.py`
- Tests: `tests/test_drive_tests_v2.py`

## Commands

Start:

```bash
python tools/elmo_lte_drive_worker.py start --name <route-or-session-name>
```

Status:

```bash
python tools/elmo_lte_drive_worker.py status
```

Mark:

```bash
python tools/elmo_lte_drive_worker.py mark "<label>"
```

Stop:

```bash
python tools/elmo_lte_drive_worker.py stop
```

Stationary validation:

```bash
python tools/elmo_lte_drive_worker.py validate --duration 190 --epoch-duration 10
python tools/verify_drive_skill_v2.py --session-id <validation-session-id>
```

## Required Streams

Each v2 session writes append-only streams under `runtime/drive-tests/<session-id>/`:

- `session.json`
- `STATE.json`
- `HEARTBEAT.json`
- `events.jsonl`
- `gps_raw.jsonl`
- `gps.jsonl`
- `lte1.jsonl`
- `lte2.jsonl`
- `ping_lte1.jsonl`
- `ping_lte2.jsonl`
- `traffic_lte1.jsonl`
- `traffic_lte2.jsonl`
- `traffic_epochs/`

Public output goes under `results-public/drive-tests/<session-id>/` and includes `REPORT.md`, `summary.json`, `timeline.csv`, `timeline.jsonl`, event/diversity CSV/JSON, and GPS map files when real fixes exist.

## Operating Rules

- Use `AUTO_DUAL_6M` unless Madis explicitly asks for another profile.
- Do not redesign the method during drives.
- Keep the START / STATUS / MARK / STOP workflow.
- Do not ask the driver to troubleshoot while moving.
- Preserve private raw identifiers locally; public reports may contain pseudonymous modem/SIM IDs, operators, cell data, and explicit GPS tracks.
- Do not modify production video routing.
- Do not start a moving drive until `tools/verify_drive_skill_v2.py` reports `PASS_DRIVE_SKILL_V2`.
- Do not conduct the next real drive automatically after verification.

## v2 Data Requirements

- GPS is sampled about 1 Hz into raw and parsed streams. Invalid fixes use null coordinates; never fake `0,0`.
- LTE telemetry is sampled about 1 Hz per interface and continues through monitor errors or deregistration.
- Operator mapping is established at START and attached to LTE, ping, and traffic records.
- Ping is path-bound from `.201`/`.202`, preferably every 0.5 s.
- Traffic keeps rolling epochs for robustness but uses about 10 s UDP windows for true receiver loss unless verified `iperf3 --json-stream` loss is available.
- STOP during an epoch must preserve partial data and label it `PARTIAL_STOPPED_BY_USER`.
- Post-stop analysis builds a 1-second UTC timeline with GPS/LTE stale cutoff at 2 s.
- Event detection is based on continuous telemetry, not minute summaries.
- Legacy first-drive data is labeled `LEGACY_COARSE_EPOCH_DATA`; do not fabricate missing GPS or 1-second telemetry.

## Handoff Gate

Only say:

```text
READY FOR NEXT DRIVE: YES
```

when verification classification is `PASS_DRIVE_SKILL_V2`.

Otherwise say:

```text
READY FOR NEXT DRIVE: NO — <specific blocker>
```
