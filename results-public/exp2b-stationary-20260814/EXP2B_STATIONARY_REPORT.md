# ELMO Experiment 2b Stationary Report

Updated: 2026-08-14T05:16:39+00:00
Current condition: B

OpenClaw made no RouterOS configuration changes. RSC imports are manual boundaries.

## Current Status

- B_lte1_6M_r1: OK exit_codes=[0]
- B_lte1_6M_r2: OK exit_codes=[0]
- B_lte1_6M_r3: OK exit_codes=[0]
- B_lte2_6M_r1: OK exit_codes=[0]
- B_lte2_6M_r2: FAILED exit_codes=[1]
- B_lte2_6M_r2_retry1: OK exit_codes=[0]

`B_lte2_6M_r2_retry1` used the same PFIFO condition, pinned server/IP,
LTE2 source path, 6M offered UDP load, 1200-byte datagrams, and 120s duration.
Receiver goodput was 4.83 Mbps, UDP loss 19.35%, UDP jitter 2.34 ms, and
path verification passed. Ping samples showed 82.3% loss during the loaded run,
with p95 122 ms among received replies.

## Evidence Boundary

- Network queue/latency evidence: collected from iPerf receiver metrics, path-bound ping, LTE telemetry, RouterOS resource state, and Exp2b queue telemetry.
- Actual video frame-age evidence: not collected in this stationary iPerf campaign.

Do not treat ping alone as proof that displayed production video latency is fixed.
