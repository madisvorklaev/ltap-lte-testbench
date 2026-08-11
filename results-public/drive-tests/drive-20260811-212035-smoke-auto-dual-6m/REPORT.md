# ELMO LTE Drive-Test Skill Smoke Test

Session: `drive-20260811-212035-smoke-auto-dual-6m`

Completed UTC: `2026-08-11T18:23:43+00:00`

## Result

`PASS_WITH_RADIO_IMPAIRMENT` - the applied skill is installed and the stationary smoke run exercised the existing collector path for dual LTE traffic, LTE telemetry, path-bound ping, and source-rule verification. LTE1 had poor radio/performance during the smoke run; LTE2 was clean.

## Path Results

| Path | UDP Mbps | UDP loss | Ping p95 | Path verification | Bands seen |
|---|---:|---:|---:|---|---|
| `lte1` | 3.370 | 36.066% | 2990.0 ms | `PASS_CONCURRENT_OTHER_LTE` | B38@20Mhz earfcn: 37900 phy-cellid: 3; B3@15Mhz earfcn: 1875 phy-cellid: 69 |
| `lte2` | 5.995 | 0.000% | 32.6 ms | `PASS_CONCURRENT_OTHER_LTE` | B7@20Mhz earfcn: 3248 phy-cellid: 171 |

## Checks

- Applied skill: `elmo-lte-drive-test`.
- Preflight: OK for `eno1`, `.201`, `.202`, RouterOS SSH, LTE monitors, pinned public iPerf server.
- Traffic: two simultaneous 75 s UDP upload paths at 6 Mbit/s with 1200-byte datagrams.
- Artifacts: local raw files preserved under `runtime/drive-tests/drive-20260811-212035-smoke-auto-dual-6m/`.
- Public sanitized summary/report written under `results-public/drive-tests/drive-20260811-212035-smoke-auto-dual-6m/`.
- No production video routing changes made.
- LTE band settings remained AUTO/blank after the test.

## Limitations

- GPS status: valid RouterOS GPS fix observed after the run, but no GPX/GeoJSON track was captured by this collector.
- This tested the skill procedure and current collector path, not a finished durable variable-length drive worker/service.
- The smoke radio result is stationary and should not be treated as production drive evidence.
