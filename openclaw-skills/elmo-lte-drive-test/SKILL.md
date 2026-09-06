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

RUTX12/RB4011 moving-drive work uses a separate focused implementation:

- Worker CLI: `tools/rutx12_drive_worker.py`
- Parser/analyzer module: `src/ltap_testbench/drive_tests/rutx12.py`
- Tests: `tests/test_rutx12_drive.py`

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

RUTX12/RB4011 fixed-load moving-drive preparation:

```bash
python tools/rutx12_drive_worker.py recompute-overnight
python tools/rutx12_drive_worker.py validate --name car-stationary-gate
python tools/rutx12_drive_worker.py start --name <session-name> --route-id <route-id> --direction <direction>
python tools/rutx12_drive_worker.py status
python tools/rutx12_drive_worker.py load-start
python tools/rutx12_drive_worker.py mark "<passenger-entered label>"
python tools/rutx12_drive_worker.py load-stop --post-idle 300
python tools/rutx12_drive_worker.py stop
python tools/rutx12_drive_worker.py verify --session-id <session-id>
python tools/rutx12_drive_worker.py analyze --session-id <session-id>
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
- For RUTX12/RB4011 tests, use fixed unshaped UDP `5,000,000 bit/s` per path,
  `1,200` byte payloads, automatic cellular band/CA selection, and stable
  labels `rut-a/path-a` and `rut-b/path-b`.
- Do not redesign the method during drives.
- Keep the START / STATUS / MARK / STOP workflow.
- Do not ask the driver to troubleshoot while moving.
- Preserve private raw identifiers locally; public reports may contain pseudonymous modem/SIM IDs, operators, cell data, and explicit GPS tracks.
- Do not modify production video routing.
- Do not start a moving drive until `tools/verify_drive_skill_v2.py` reports `PASS_DRIVE_SKILL_V2`.
- Do not start a RUTX12 moving run until `tools/rutx12_drive_worker.py validate`
  ends with `READY FOR RUTX12 MOVING TEST: YES` and Madis explicitly authorizes
  departure after the physical safety checklist.
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

For RUTX12/RB4011 moving-drive handoff, say exactly one of:

```text
READY FOR RUTX12 MOVING TEST: YES
```

or:

```text
READY FOR RUTX12 MOVING TEST: NO - <specific blocker>
```

Always state that this is fixed-rate iPerf evidence, not GCC, encoded video,
one-way video latency, or a production remote-driving qualification.
