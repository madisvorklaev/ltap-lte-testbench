# FG621 firmware A/B test fg621-firmware-ab-thick-pigtails

Updated: 2026-08-10T17:25:34+00:00

A-side reference: `mixed-lte6-thick-pigtails-pre-firmware`.
FG621 firmware before: `16121.1034.00.01.01.04`.
Latest stable offered: `16121.1034.00.01.01.10`.
FG621 firmware after: ``.
RouterOS: `7.24rc3`.

| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |
|---|---|---|---:|---:|---:|---:|---:|---|
| F1 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| F1 | FG621-EA | 3 |  |  |  |  |  | PENDING |
| F2 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| F2 | FG621-EA | 8 |  |  |  |  |  | PENDING |
| F3 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| F3 | FG621-EA | 7 |  |  |  |  |  | PENDING |
| L3-1 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L3-1 | FG621-EA | 3 |  |  |  |  |  | PENDING |
| L3-2 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L3-2 | FG621-EA | 3 |  |  |  |  |  | PENDING |
| L3-3 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L3-3 | FG621-EA | 3 |  |  |  |  |  | PENDING |
| L8-1 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| L8-1 | FG621-EA | 8 |  |  |  |  |  | PENDING |
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
| B3 | 4.94 |  | 17.532 |  | 122 |  | -94 |  | 3 |  |
| B8 | 5.941 |  | 0.955 |  | 41.7 |  | -91 |  | 8 |  |
| B7 | 5.573 |  | 7.096 |  | 104 |  | -105 |  | 13 |  |

| Test | Pre R11e loss | Post R11e loss | Pre p95 | Post p95 | Control stable? |
|---|---:|---:|---:|---:|---|
| F1 | 0.206 |  | 42.8 |  | True |
| F2 | 0.128 |  | 35.5 |  | True |
| F3 | 0.778 |  | 41.7 |  | True |

## Conclusions

1. FG621 firmware before: `16121.1034.00.01.01.04`.
2. Latest stable offered: `16121.1034.00.01.01.10`.
3. Firmware installed after: ``.
4. B3 category: `PENDING`.
5. B3 throughput/loss/p95 delta: -4.94 Mbps, -17.532 pp loss, -122 ms p95.
6. B8 remained good: `True`.
7. B7 change: see B7 row above.
8. R11e control stayed stable unless marked otherwise in the control table.
9. Firmware attribution depends on the B3 and B8 deltas above.
10. Unrestricted FG621 band selection is acceptable only if B3 no longer shows impairment.
11. R11e firmware should not be tested from this campaign unless separately requested.
12. Original bands restored: `false`.

FIRMWARE_NO_MEANINGFUL_EFFECT
