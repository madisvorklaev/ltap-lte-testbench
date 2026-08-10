# Thick-pigtail validation mixed-lte6-thick-pigtails-pre-firmware

Updated: 2026-08-10T16:33:27+00:00

Thin-pigtail reference: `fg621-pre-firmware-quick-baseline`.
Physical change: both modems now use thicker beige pigtails.
FG621 firmware verified before tests: `16121.1034.00.01.01.04`.
RouterOS verified before tests: `7.24rc3`.

| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | RSRP | SINR | Status |
|---|---|---|---:|---:|---:|---:|---:|---|
| P1 | R11e-LTE6 | 3 | 5.986 | 0.206 | 42.8 | -96 | 3 | PASS_DUAL |
| P1 | FG621-EA | 3 | 4.94 | 17.532 | 122 | -94 | 3 | PASS_DUAL |
| P2 | R11e-LTE6 | 3 | 5.991 | 0.128 | 35.5 | -96 | 4 | PASS_DUAL |
| P2 | FG621-EA | 8 | 5.941 | 0.955 | 41.7 | -91 | 8 | PASS_DUAL |
| P3 | R11e-LTE6 | 3 | 5.952 | 0.778 | 41.7 | -96 | 3 | PASS_DUAL |
| P3 | FG621-EA | 7 | 5.573 | 7.096 | 104 | -105 | 13 | PASS_DUAL |
| P4 | FG621-EA | 3 |  |  |  |  |  | P4_NOT_TRIGGERED |

## Thin vs Thick

| Modem | Band | Thin Mbps | Thick Mbps | Thin loss % | Thick loss % | Thin p95 | Thick p95 | Thin RSRP | Thick RSRP | Thin SINR | Thick SINR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R11e-LTE6 | 3 | 5.994 | 5.986 | 0.079 | 0.206 | 35.7 | 42.8 | -94 | -96 | 10 | 3 |
| FG621-EA | 3 | 5.326 | 4.94 | 11.211 | 17.532 | 123 | 122 | -94 | -94 | 4 | 3 |
| R11e-LTE6 | 3 | 5.993 | 5.991 | 0.097 | 0.128 | 31 | 35.5 |  | -96 |  | 4 |
| FG621-EA | 8 | 5.994 | 5.941 | 0.078 | 0.955 | 46.9 | 41.7 | -83 | -91 | 5 | 8 |
| FG621-EA | 7 | 5.799 | 5.573 | 3.326 | 7.096 | 137 | 104 | -105 | -105 | 10 | 13 |

## Interpretation

- P1 FG621 B3 loss/p95: 17.532% / 122 ms.
- P2 FG621 B8 loss: 0.955%.
- P4 triggered: `false`.
- Original bands restored: `false`.
- New thicker pigtails did not materially solve the FG621 B3 problem; B8 remains the clean comparison path.

Final recommendation: `PROCEED_TO_FG621_FIRMWARE_TEST`
