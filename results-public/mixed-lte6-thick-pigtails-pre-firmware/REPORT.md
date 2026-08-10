# Thick-pigtail validation mixed-lte6-thick-pigtails-pre-firmware

Updated: 2026-08-10T16:15:02+00:00

Thin-pigtail reference: `fg621-pre-firmware-quick-baseline`.
Physical change: both modems now use thicker beige pigtails.
FG621 firmware verified before tests: `16121.1034.00.01.01.04`.
RouterOS verified before tests: `7.24rc3`.

| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |
|---|---|---|---:|---:|---:|---:|---:|---|
| P1 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| P1 | FG621-EA | 3 |  |  |  |  |  | PENDING |
| P2 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| P2 | FG621-EA | 8 |  |  |  |  |  | PENDING |
| P3 | R11e-LTE6 | 3 |  |  |  |  |  | PENDING |
| P3 | FG621-EA | 7 |  |  |  |  |  | PENDING |
| P4 | FG621-EA | 3 |  |  |  |  |  | PENDING |

## Thin vs Thick

| Modem | Band | Thin Mbps | Thick Mbps | Thin loss % | Thick loss % | Thin p95 | Thick p95 | Thin RSRP | Thick RSRP | Thin SINR | Thick SINR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R11e-LTE6 | 3 | 5.994 |  | 0.079 |  | 35.7 |  | -94 |  | 10 |  |
| FG621-EA | 3 | 5.326 |  | 11.211 |  | 123 |  | -94 |  | 4 |  |
| R11e-LTE6 | 3 | 5.993 |  | 0.097 |  | 31 |  |  |  |  |  |
| FG621-EA | 8 | 5.994 |  | 0.078 |  | 46.9 |  | -83 |  | 5 |  |
| FG621-EA | 7 | 5.799 |  | 3.326 |  | 137 |  | -105 |  | 10 |  |

## Interpretation

- P1 FG621 B3 loss/p95: % /  ms.
- P2 FG621 B8 loss: %.
- P4 triggered: `false`.
- Original bands restored: `false`.
- New thicker pigtails did not materially solve the FG621 B3 problem; B8 remains the clean comparison path.

Final recommendation: `PROCEED_TO_FG621_FIRMWARE_TEST`
