# LtAP Stability stability-7.24rc3

Updated: 2026-08-08T20:19:47+00:00

This stability report is generated incrementally. Final production recommendations are withheld until all phases are terminal.

| Item | Phase | Candidate | Repeat | State | LTE1 band | LTE2 band | Load | Status | LTE1 Mbps | LTE1 loss % | LTE1 p95 ms | LTE2 Mbps | LTE2 loss % | LTE2 p95 ms |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1-P1 | PHASE_A_REPEATABILITY | P1 | 1 | SKIPPED_BAND_UNAVAILABLE | 3 | 3 | 6M/6M |  |  |  |  |  |  |  |
| A1-P2 | PHASE_A_REPEATABILITY | P2 | 1 | COMPLETE | 3 | 20 | 6M/6M | PASS_DUAL | 5.98190504401483 | 0.2928 | 36.0 | 5.9944900795870115 | 0.08186666666666667 | 31.3 |
| A1-P3 | PHASE_A_REPEATABILITY | P3 | 1 | COMPLETE | 3 | 7 | 6M/6M | PASS_DUAL | 5.993729214833388 | 0.0928 | 34.3 | 5.986922195939671 | 0.20853333333333332 | 37.9 |
| A1-P4 | PHASE_A_REPEATABILITY | P4 | 1 | COMPLETE | 3,20 | 3,7,20 | 6M/6M | PASS_DUAL | 5.968857247056297 | 0.5096 | 40.8 | 5.991084574632134 | 0.13946666666666666 | 33.6 |
| A2-P4 | PHASE_A_REPEATABILITY | P4 | 2 | FAILED_AFTER_RETRIES | 3,20 | 3,7,20 | 6M/6M | FAIL_IPERF_OR_PATH |  |  | 36.7 |  |  | 33.9 |
| A2-P3 | PHASE_A_REPEATABILITY | P3 | 2 | COMPLETE | 3 | 7 | 6M/6M | PASS_DUAL | 5.984051338325494 | 0.25706666666666667 | 36.5 | 5.95405767062472 | 0.7546666666666667 | 64.0 |
| A2-P2 | PHASE_A_REPEATABILITY | P2 | 2 | FAILED_AFTER_RETRIES | 3 | 20 | 6M/6M | FAIL_IPERF_OR_PATH |  |  | 19.4 |  |  | 31.3 |
| A2-P1 | PHASE_A_REPEATABILITY | P1 | 2 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.987120816142432 | 0.20453333333333334 | 36.9 | 5.958620145706645 | 0.6802666666666667 | 34.1 |
| A3-P2 | PHASE_A_REPEATABILITY | P2 | 3 | COMPLETE | 3 | 20 | 6M/6M | PASS_DUAL | 5.97821865978874 | 0.3536 | 34.7 | 5.99738260358391 | 0.0349335196454381 | 30.9 |
| A3-P4 | PHASE_A_REPEATABILITY | P4 | 3 | FAILED_AFTER_RETRIES | 3,20 | 3,7,20 | 6M/6M | FAIL_IPERF_OR_PATH |  |  | 3212.0 | 5.9698886151501585 | 0.49493333333333334 | 33.8 |
| A3-P1 | PHASE_A_REPEATABILITY | P1 | 3 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.980677225789583 | 0.3122666666666667 | 44.0 | 5.995640852346307 | 0.0632 | 33.8 |
| A3-P3 | PHASE_A_REPEATABILITY | P3 | 3 | COMPLETE | 3 | 7 | 6M/6M | PASS_DUAL | 5.950584251997252 | 0.812 | 38.5 | 5.965591562354438 | 0.5624 | 39.0 |
| B-P1 | PHASE_B_ENDURANCE | P1 | 1 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.970392343940047 | 0.4889777777777778 | 43.0 | 5.992785268884175 | 0.11671111111111111 | 33.5 |
| B-P2 | PHASE_B_ENDURANCE | P2 | 1 | COMPLETE | 3 | 20 | 6M/6M | PASS_DUAL | 5.898151835453474 | 1.69413634513128 | 545.0 | 5.960637490531073 | 0.6542233852860183 | 32.7 |
| C-P1-6_6 | PHASE_C_HEADROOM | P1 | 1 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.984489972078469 | 0.2336 | 51.0 | 5.992429579481392 | 0.10506666666666667 | 39.7 |
| C-P1-8_8 | PHASE_C_HEADROOM | P1 | 2 | COMPLETE | 3 | 3 | 8M/8M | PASS_DUAL | 7.892068006999974 | 1.1388 | 1184.0 | 7.982043678424563 | 0.12800153601843223 | 48.8 |
| C-P1-8_6 | PHASE_C_HEADROOM | P1 | 3 | COMPLETE | 3 | 3 | 8M/6M | PASS_DUAL | 7.956114608574129 | 0.5252 | 275.0 | 5.995469820009371 | 0.05653333333333333 | 33.7 |
| C-P1-6_8 | PHASE_C_HEADROOM | P1 | 4 | COMPLETE | 3 | 3 | 6M/8M | PASS_DUAL | 5.973528004293693 | 0.4266666666666667 | 37.0 | 7.982186150994772 | 0.204 | 36.7 |
| C-P4-6_6 | PHASE_C_HEADROOM | P4 | 1 | COMPLETE | 3,20 | 3,7,20 | 6M/6M | PASS_DUAL | 5.97590604936976 | 0.384 | 38.7 | 5.98897188156908 | 0.16586666666666666 | 34.0 |
| C-P4-8_8 | PHASE_C_HEADROOM | P4 | 2 | COMPLETE | 3,20 | 3,7,20 | 8M/8M | PASS_DUAL | 7.934611160969696 | 0.772 | 1089.0 | 7.9873531655242305 | 0.1232 | 44.8 |
| C-P4-8_6 | PHASE_C_HEADROOM | P4 | 3 | COMPLETE | 3,20 | 3,7,20 | 8M/6M | PASS_DUAL | 7.743870317486645 | 2.1092 | 1285.0 | 5.995567358632573 | 0.05226666666666667 | 37.0 |
| C-P4-6_8 | PHASE_C_HEADROOM | P4 | 4 | COMPLETE | 3,20 | 3,7,20 | 6M/8M | PASS_DUAL | 5.977093319824426 | 0.3616 | 38.1 | 7.984532225043282 | 0.174 | 35.4 |
| D-P1 | PHASE_D_BURST | P1 | 1 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.980808097761954 | 0.3060148148148148 | 35.8 | 5.9970327415048645 | 0.035318602236686786 | 30.1 |
| D-P4 | PHASE_D_BURST | P4 | 1 | COMPLETE | 3,20 | 3,7,20 | 6M/6M | PASS_DUAL | 5.988655608317679 | 0.18157037037037038 | 108.0 | 5.996857467727183 | 0.045037037037037035 | 34.7 |
| E-P4 | PHASE_E_DYNAMIC_OBSERVATION | P4 | 1 | FAILED_AFTER_RETRIES | 3,20 | 3,7,20 | 6M/6M | FAIL_IPERF_OR_PATH |  |  | 199.0 |  |  | 35.7 |
| F-P1-LTE1-1 | PHASE_F_RECOVERY | P1 | 1 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.991693310661399 | 0.034666666666666665 | 56.9 | 5.993476825545599 |  | 32.6 |
| F-P1-LTE1-2 | PHASE_F_RECOVERY | P1 | 2 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.995064331753325 |  | 71.8 | 5.993980085269304 |  | 31.6 |
| F-P1-LTE2-1 | PHASE_F_RECOVERY | P1 | 3 | COMPLETE | 3 | 3 | 6M/6M | PASS_DUAL | 5.988245937366147 | 0.10133333333333333 | 64.8 | 5.989469394165466 | 0.08266666666666667 | 31.8 |
| F-P1-LTE2-2 | PHASE_F_RECOVERY | P1 | 4 | FAILED_AFTER_RETRIES | 3 | 3 | 6M/6M | FAIL_IPERF_OR_PATH |  |  |  | 5.99242392115132 | 0.064 | 31.8 |

## Final Analysis

Campaign terminal state: COMPLETE. Mandatory items terminal: 29/29. Result split: 23 COMPLETE, 5 FAILED_AFTER_RETRIES, 1 SKIPPED_BAND_UNAVAILABLE. Original band settings were restored to AUTO/AUTO. No push was pending at completion.

Important implementation caveat: Phase D and Phase F in this run are useful smoke evidence, but they are not a full implementation of the requested bitrate-step burst profile or modem-by-modem AUTO/reapply recovery timing. Treat those two phases as preliminary evidence only.

### Candidate Aggregate

| Candidate | Complete runs | Failed/skipped | Worst loss % | Worst p95 ms | Median worst-path loss % | Median worst-path p95 ms | Grade | Rank |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| P3 fixed B3/B7 | 3 | 0 | 0.812 | 64.0 | 0.755 | 39.0 | GOOD | 1 |
| P1 fixed B3/B3 | 11 | 2 | 1.139 | 1184.0 | 0.312 | 51.0 | DEGRADED | 2 |
| P4 restricted dynamic | 6 | 3 | 2.109 | 1285.0 | 0.447 | 74.4 | DEGRADED | 3 |
| P2 fixed B3/B20 | 3 | 2 | 1.694 | 545.0 | 0.354 | 36.0 | DEGRADED | 4 |

The low-latency repeatability winner in this stationary test is P3, fixed LTE1=B3 and LTE2=B7. It completed all three Phase A repeats with both paths under 1% loss and worst p95 64 ms.

P1 remains a strong conservative stationary candidate at 6/6 and in the 30-minute endurance run, but it had one B3/B3 registration skip at campaign start and becomes queue-sensitive when LTE1 is pushed to 8 Mbit/s. P2 is not as robust as the earlier 5-minute matrix suggested: one Phase A repeat failed after retries and the 30-minute endurance run showed LTE1 loss about 1.69% and p95 about 545 ms. P4 is useful as a restricted dynamic policy but was not stable enough here: two Phase A repeats failed after retries, Phase E failed after retries, and the 8/6 headroom case had LTE1 loss above 2% with p95 above 1.2 s.

### Final Questions

1. B3/B3 stayed clean in its successful 10-minute repeats and 30-minute endurance run, but the first P1 repeat skipped because LTE1 did not register/verify on B3.
2. B3/B20 did not remain as clean as the original 5-minute result. It had one repeat failure and degraded in endurance on LTE1.
3. B3/B7 was the most stable tested production candidate in Phase A.
4. P4 did not remain stable enough; it failed repeatability and dynamic-observation attempts.
5. Best worst-path p95 latency among repeatability candidates: P3.
6. Best worst-path UDP loss among candidates with multiple successful runs: P1 median, but P3 had the best reliability/latency balance.
7. Smallest practical repeat-to-repeat variation: P3.
8. Queueing starts clearly when LTE1 is offered 8 Mbit/s. P1 8/8 p95 reached about 1184 ms; P4 8/8 and 8/6 reached about 1089-1285 ms.
9. Burst recovery was not conclusively tested; Phase D used fixed 6/6 smoke loads and should be rerun with real bitrate step changes.
10. No successful result shows a clear LTE disconnect summary in this compact table, but several FAIL_IPERF_OR_PATH items need raw-artifact review before ruling out transient path/radio drops.
11. P4 natural dynamic observation was not successful; E-P4 failed after retries, so stationary reselection evidence is inconclusive.
12. Remote band-change recovery was not conclusively tested; Phase F produced useful P1 60-second smoke data but did not perform the requested AUTO/reapply timing sequence.
13. Next moving-vehicle candidate: fixed LTE1=B3 and LTE2=B7. Secondary conservative candidate: fixed B3/B3. Do not use B38, and do not allow B7 on LTE1.
14. Original AUTO band values were restored at the end.
15. No unexpected RouterOS persistent configuration change is reported by the runner; a deeper config-fingerprint audit should still be reviewed before production rollout.

### Recommendations

Stationary best: P3 fixed LTE1=B3, LTE2=B7.

Moving-vehicle candidate: start with P3 fixed B3/B7 for the first controlled moving test because it was clean and repeatable here. Keep P4 as a later experiment only after the dynamic policy is debugged.

Emergency conservative policy: exclude B38 completely and exclude B7 from LTE1. Use either fixed B3/B3 or fixed B3/B7 depending on whether coverage diversity or the simplest known-good state matters more.
