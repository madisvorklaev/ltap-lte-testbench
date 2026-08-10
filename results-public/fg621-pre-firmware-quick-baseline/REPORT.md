# FG621 pre-firmware quick baseline fg621-pre-firmware-quick-baseline

Updated: 2026-08-10T04:50:58+00:00

FG621 firmware expected/verified before tests: `16121.1034.00.01.01.04`.
RouterOS expected/verified before tests: `7.24rc3`.

| Test | Modem | Band | Mbps | UDP loss % | p95 RTT | Registration |
|---|---|---|---:|---:|---:|---|
| Q1 | R11e-LTE6 | 3 | 5.994 | 0.079 | 35.7 | REGISTERED |
| Q1 | FG621-EA | 3 | 5.326 | 11.211 | 123 | REGISTERED |
| Q2 | R11e-LTE6 | 3 | 5.993 | 0.097 | 31 | REGISTERED |
| Q2 | FG621-EA | 8 | 5.994 | 0.078 | 46.9 | REGISTERED |
| Q3 | R11e-LTE6 | 3 |  |  | 34.5 | REGISTERED |
| Q3 | FG621-EA | 7 | 5.799 | 3.326 | 137 | REGISTERED |

## Required Statements

- Fresh pre-upgrade FG621 B3 result: 5.326 Mbps, 11.211% UDP loss, p95 123 ms.
- Fresh pre-upgrade R11e-LTE6 B3 control: 5.994 Mbps, 0.079% UDP loss, p95 35.7 ms.
- Fresh pre-upgrade FG621 B8 result: 5.994 Mbps, 0.078% UDP loss, p95 46.9 ms.
- FG621 B7 availability: REGISTERED.
- FG621 firmware remained `16121.1034.00.01.01.04`.
- RouterOS remained `7.24rc3`.
- Original bands restored: `true`.
