# ELMO Experiment 2b Stationary Report

Updated: 2026-08-14T06:14:33+00:00
Current condition: C

RouterOS state for this C run was CAKE 5M. The CAKE RSC was imported by OpenClaw immediately before this run at Madis's direct request; the test runner itself made no further RouterOS configuration changes.

## Current Status

- C_lte1_6M_r1: OK exit_codes=[0]
- C_lte1_6M_r2: OK exit_codes=[0]
- C_lte1_6M_r3: OK exit_codes=[0]
- C_lte2_6M_r1: OK exit_codes=[0]
- C_lte2_6M_r2: OK exit_codes=[0]
- C_lte2_6M_r3: OK exit_codes=[0]
- C_dual_6M_r1: FAILED exit_codes=[1, 0]

## Evidence Boundary

- Network queue/latency evidence: collected from iPerf receiver metrics, path-bound ping, LTE telemetry, RouterOS resource state, and Exp2b queue telemetry.
- Actual video frame-age evidence: not collected in this stationary iPerf campaign.

Do not treat ping alone as proof that displayed production video latency is fixed.
