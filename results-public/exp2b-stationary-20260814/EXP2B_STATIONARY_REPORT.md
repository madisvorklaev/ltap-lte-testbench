# ELMO Experiment 2b Stationary Report

Updated: 2026-08-14T04:54:15+00:00
Current condition: B

OpenClaw made no RouterOS configuration changes. RSC imports are manual boundaries.

## Current Status

- B_lte1_6M_r1: OK exit_codes=[0]
- B_lte1_6M_r2: OK exit_codes=[0]
- B_lte1_6M_r3: OK exit_codes=[0]
- B_lte2_6M_r1: OK exit_codes=[0]
- B_lte2_6M_r2: FAILED exit_codes=[1]

Paused at `B_lte2_6M_r2` because the pinned public iPerf server returned:
`the server is busy running a test. try again later`

Per the experiment procedure this invalid attempt was preserved and the campaign
was stopped instead of silently retrying, changing server/IP, or changing ports
outside the pinned campaign.

## Evidence Boundary

- Network queue/latency evidence: collected from iPerf receiver metrics, path-bound ping, LTE telemetry, RouterOS resource state, and Exp2b queue telemetry.
- Actual video frame-age evidence: not collected in this stationary iPerf campaign.

Do not treat ping alone as proof that displayed production video latency is fixed.
