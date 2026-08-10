# FG621 firmware A/B test fg621-firmware-ab-thick-pigtails

Updated: 2026-08-10T18:34:42+00:00

A-side reference: `mixed-lte6-thick-pigtails-pre-firmware`.
FG621 firmware before: `16121.1034.00.01.01.04`.
Latest stable offered: `16121.1034.00.01.01.10`.
FG621 firmware after: `16121.1034.00.01.01.10`.
RouterOS: `7.24rc3`.

| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |
|---|---|---|---:|---:|---:|---:|---:|---|
| F1 | R11e-LTE6 | 3 | 5.995 | 0.068 | 36.6 | -96 | 4 | PASS_DUAL |
| F1 | FG621-EA | 3 | 5.491 | 8.474 | 114 | -95 | 3 | PASS_DUAL |
| F2 | R11e-LTE6 | 3 | 5.993 | 0.096 | 37.8 | -96 | 4 | PASS_DUAL |
| F2 | FG621-EA | 8 | 5.993 | 0.101 | 48.9 | -89 | 5 | PASS_DUAL |
| F3 | R11e-LTE6 | 3 |  |  | 34.5 | -96 | 4 | FAIL_IPERF_OR_PATH |
| F3 | FG621-EA | 7 | 5.571 | 7.077 | 101 | -105 | 11 | FAIL_IPERF_OR_PATH |
| L3-1 | R11e-LTE6 | 3 | 5.987 | 0.206 | 37.7 | -96 | 5 | PASS_DUAL |
| L3-1 | FG621-EA | 3 | 4.957 | 17.266 | 135 | -95 | 3 | PASS_DUAL |
| L3-2 | R11e-LTE6 | 3 | 5.994 | 0.096 | 39.7 | -96 | 5 | PASS_DUAL |
| L3-2 | FG621-EA | 3 | 4.93 | 17.751 | 137 | -95 | 3 | PASS_DUAL |
| L3-3 | R11e-LTE6 | 3 |  |  |  |  |  | CONDITIONAL_NOT_TRIGGERED |
| L3-3 | FG621-EA | 3 |  |  |  |  |  | CONDITIONAL_NOT_TRIGGERED |
| L8-1 | R11e-LTE6 | 3 |  |  |  |  |  | CONDITIONAL_NOT_TRIGGERED |
| L8-1 | FG621-EA | 8 |  |  |  |  |  | CONDITIONAL_NOT_TRIGGERED |
| L8-2 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L8-2 | FG621-EA | 8 |  |  |  |  |  | PENDING |
| L8-3 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L8-3 | FG621-EA | 8 |  |  |  |  |  | PENDING |
| STAIR-4M | FG621-EA | 3 |  |  |  |  |  | PENDING |
| STAIR-6M | FG621-EA | 3 |  |  |  |  |  | PENDING |
| STAIR-8M | FG621-EA | 3 |  |  |  |  |  | PENDING |
| STAIR-10M | FG621-EA | 3 |  |  |  |  |  | PENDING |
| STAIR-12M | FG621-EA | 3 |  |  |  |  |  | PENDING |

## FG621 A/B

| FG621 band | Pre-FW Mbps | Post-FW Mbps | Pre loss % | Post loss % | Pre p95 | Post p95 | Pre RSRP | Post RSRP | Pre SINR | Post SINR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B3 | 4.94 | 5.491 | 17.532 | 8.474 | 122 | 114 | -94 | -95 | 3 | 3 |
| B8 | 5.941 | 5.993 | 0.955 | 0.101 | 41.7 | 48.9 | -91 | -89 | 8 | 5 |
| B7 | 5.573 | 5.571 | 7.096 | 7.077 | 104 | 101 | -105 | -105 | 13 | 11 |

| Test | Pre R11e loss | Post R11e loss | Pre p95 | Post p95 | Control stable? |
|---|---:|---:|---:|---:|---|
| F1 | 0.206 | 0.068 | 42.8 | 36.6 | True |
| F2 | 0.128 | 0.096 | 35.5 | 37.8 | True |
| F3 | 0.778 |  | 41.7 | 34.5 | True |

## Conclusions

1. FG621 firmware before: `16121.1034.00.01.01.04`.
2. Latest stable offered: `16121.1034.00.01.01.10`.
3. Firmware installed after: `16121.1034.00.01.01.10`.
4. B3 category: `PARTIAL_B3_IMPROVEMENT`.
5. B3 throughput/loss/p95 delta: 0.551 Mbps, -9.058 pp loss, -8 ms p95.
6. B8 remained good: `True`.
7. B7 change: see B7 row above.
8. R11e control stayed stable unless marked otherwise in the control table.
9. Firmware attribution depends on the B3 and B8 deltas above.
10. Unrestricted FG621 band selection is acceptable only if B3 no longer shows impairment.
11. R11e firmware should not be tested from this campaign unless separately requested.
12. Original bands restored: `false`.

FIRMWARE_PARTIAL_IMPROVEMENT
