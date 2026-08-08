# LtAP Stability stability-7.24rc3

Updated: 2026-08-08T12:35:31+00:00

This stability report is generated incrementally. Final production recommendations are withheld until all phases are terminal.

| Item | Phase | Candidate | Repeat | State | LTE1 band | LTE2 band | Load | Status | LTE1 Mbps | LTE1 loss % | LTE1 p95 ms | LTE2 Mbps | LTE2 loss % | LTE2 p95 ms |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1-P1 | PHASE_A_REPEATABILITY | P1 | 1 | SKIPPED_BAND_UNAVAILABLE | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| A1-P2 | PHASE_A_REPEATABILITY | P2 | 1 | COMPLETE | 3 | 20 | 6M/6M | PASS_DUAL | 5.98190504401483 | 0.2928 | 36.0 | 5.9944900795870115 | 0.08186666666666667 | 31.3 |
| A1-P3 | PHASE_A_REPEATABILITY | P3 | 1 | COMPLETE | 3 | 7 | 6M/6M | PASS_DUAL | 5.993729214833388 | 0.0928 | 34.3 | 5.986922195939671 | 0.20853333333333332 | 37.9 |
| A1-P4 | PHASE_A_REPEATABILITY | P4 | 1 | COMPLETE | 3,20 | 3,7,20 | 6M/6M | PASS_DUAL | 5.968857247056297 | 0.5096 | 40.8 | 5.991084574632134 | 0.13946666666666666 | 33.6 |
| A2-P4 | PHASE_A_REPEATABILITY | P4 | 2 | FAILED_AFTER_RETRIES | 3,20 | 3,7,20 | 6M/6M | FAIL_IPERF_OR_PATH |  |  | 36.7 |  |  | 33.9 |
| A2-P3 | PHASE_A_REPEATABILITY | P3 | 2 | COMPLETE | 3 | 7 | 6M/6M | PASS_DUAL | 5.984051338325494 | 0.25706666666666667 | 36.5 | 5.95405767062472 | 0.7546666666666667 | 64.0 |
| A2-P2 | PHASE_A_REPEATABILITY | P2 | 2 | PENDING | 3 | 20 | 6M/6M |  |  |  |  |  |  |  |
| A2-P1 | PHASE_A_REPEATABILITY | P1 | 2 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| A3-P2 | PHASE_A_REPEATABILITY | P2 | 3 | PENDING | 3 | 20 | 6M/6M |  |  |  |  |  |  |  |
| A3-P4 | PHASE_A_REPEATABILITY | P4 | 3 | PENDING | 3,20 | 3,7,20 | 6M/6M |  |  |  |  |  |  |  |
| A3-P1 | PHASE_A_REPEATABILITY | P1 | 3 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| A3-P3 | PHASE_A_REPEATABILITY | P3 | 3 | PENDING | 3 | 7 | 6M/6M |  |  |  |  |  |  |  |
| B-P1 | PHASE_B_ENDURANCE | P1 | 1 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| B-P2 | PHASE_B_ENDURANCE | P2 | 1 | PENDING | 3 | 20 | 6M/6M |  |  |  |  |  |  |  |
| C-P1-6_6 | PHASE_C_HEADROOM | P1 | 1 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| C-P1-8_8 | PHASE_C_HEADROOM | P1 | 2 | PENDING | 3 | 3 | 8M/8M |  |  |  |  |  |  |  |
| C-P1-8_6 | PHASE_C_HEADROOM | P1 | 3 | PENDING | 3 | 3 | 8M/6M |  |  |  |  |  |  |  |
| C-P1-6_8 | PHASE_C_HEADROOM | P1 | 4 | PENDING | 3 | 3 | 6M/8M |  |  |  |  |  |  |  |
| C-P4-6_6 | PHASE_C_HEADROOM | P4 | 1 | PENDING | 3,20 | 3,7,20 | 6M/6M |  |  |  |  |  |  |  |
| C-P4-8_8 | PHASE_C_HEADROOM | P4 | 2 | PENDING | 3,20 | 3,7,20 | 8M/8M |  |  |  |  |  |  |  |
| C-P4-8_6 | PHASE_C_HEADROOM | P4 | 3 | PENDING | 3,20 | 3,7,20 | 8M/6M |  |  |  |  |  |  |  |
| C-P4-6_8 | PHASE_C_HEADROOM | P4 | 4 | PENDING | 3,20 | 3,7,20 | 6M/8M |  |  |  |  |  |  |  |
| D-P1 | PHASE_D_BURST | P1 | 1 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| D-P4 | PHASE_D_BURST | P4 | 1 | PENDING | 3,20 | 3,7,20 | 6M/6M |  |  |  |  |  |  |  |
| E-P4 | PHASE_E_DYNAMIC_OBSERVATION | P4 | 1 | PENDING | 3,20 | 3,7,20 | 6M/6M |  |  |  |  |  |  |  |
| F-P1-LTE1-1 | PHASE_F_RECOVERY | P1 | 1 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| F-P1-LTE1-2 | PHASE_F_RECOVERY | P1 | 2 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| F-P1-LTE2-1 | PHASE_F_RECOVERY | P1 | 3 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| F-P1-LTE2-2 | PHASE_F_RECOVERY | P1 | 4 | PENDING | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
