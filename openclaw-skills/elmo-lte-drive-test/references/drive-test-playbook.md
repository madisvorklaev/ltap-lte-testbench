# ELMO LTE Drive-Test v2 Playbook

This repo copy tracks the live OpenClaw skill. The maintained implementation is:

- `tools/elmo_lte_drive_worker.py`
- `src/ltap_testbench/drive_tests/v2.py`
- `tools/verify_drive_skill_v2.py`

Use `AUTO_DUAL_6M`, collect GPS/LTE/ping continuously, keep UDP loss windows at 10 seconds unless `iperf3 --json-stream` is verified to provide true per-second receiver loss, and preserve partial STOP data.

Before the next moving drive, run stationary validation and require `PASS_DRIVE_SKILL_V2`.
