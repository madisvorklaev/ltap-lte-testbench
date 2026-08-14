# ELMO Experiment 2b Stationary Report

Updated: 2026-08-14T05:32:38+00:00
Current condition: B

OpenClaw made no RouterOS configuration changes. RSC imports are manual boundaries.

## Current Status

- B_lte1_6M_r1: OK exit_codes=[0]
- B_lte1_6M_r2: OK exit_codes=[0]
- B_lte1_6M_r3: OK exit_codes=[0]
- B_lte2_6M_r1: OK exit_codes=[0]
- B_lte2_6M_r2: FAILED exit_codes=[1]
- B_lte2_6M_r2_retry1: OK exit_codes=[0]
- B_restart1_lte1_6M_r1: OK exit_codes=[0]
- B_restart1_lte1_6M_r2: OK exit_codes=[0]
- B_restart1_lte1_6M_r3: FAILED exit_codes=[1]

Fresh PFIFO restart `B_restart1` stopped at LTE1 repeat 3. The LTE1 path
verification passed, but iPerf failed with `unable to receive results:`. During
that run ping showed severe loaded loss/latency (60.9% loss, p95 7159 ms among
received replies), and LTE1 changed radio state from B1 to B38. This attempt is
preserved as invalid/inconclusive for B-sequence repeatability, and the
sequence was stopped instead of continuing into LTE2/dual runs.

## Evidence Boundary

- Network queue/latency evidence: collected from iPerf receiver metrics, path-bound ping, LTE telemetry, RouterOS resource state, and Exp2b queue telemetry.
- Actual video frame-age evidence: not collected in this stationary iPerf campaign.

Do not treat ping alone as proof that displayed production video latency is fixed.
