# ELMO LTE Drive-Test v2 Playbook

This repo copy tracks the live OpenClaw skill. The maintained implementation is:

- `tools/elmo_lte_drive_worker.py`
- `src/ltap_testbench/drive_tests/v2.py`
- `tools/verify_drive_skill_v2.py`

Use `AUTO_DUAL_6M`, collect GPS/LTE/ping continuously, keep UDP loss windows at 10 seconds unless `iperf3 --json-stream` is verified to provide true per-second receiver loss, and preserve partial STOP data.

Before the next moving drive, run stationary validation and require `PASS_DRIVE_SKILL_V2`.

## RUTX12/RB4011 Moving-Drive Addendum

For the RB4011 plus two-RUTX12 topology, use:

- `tools/rutx12_drive_worker.py`
- `src/ltap_testbench/drive_tests/rutx12.py`
- `tests/test_rutx12_drive.py`

The pinned stationary reference is
`20260905T195803Z-overnight-auto-dual5m-soak` at
`b3689512f91683fdcaf62f49f333cb2c35823cff`. Recompute its whole-run metrics
from raw epoch evidence with:

```bash
python tools/rutx12_drive_worker.py recompute-overnight
```

Preserve the defensible claim boundary: the separated RUTX12/RB4011 system
showed better observed endurance than the specific LtAP/R11l-LTE7 failure, but
it did not demonstrate better upload quality in general. Historical LtAP runs
are descriptive context only, not a method-matched control.

RUTX12 traffic is two independent source-bound UDP iPerf3 clients, one per path,
with exact integer rate `5,000,000 bit/s`, `1,200` byte payloads, automatic
cellular band/CA selection, no queue/shaper/CAKE/adaptive controller, and no
cross-path failover. Use `rut-a/path-a` and `rut-b/path-b`; do not rename these
to `lte1/lte2` in new RUTX-specific raw records.

Before any road run, complete the stationary live gate and end with exactly:

```text
READY FOR RUTX12 MOVING TEST: YES
```

or:

```text
READY FOR RUTX12 MOVING TEST: NO - <specific blocker>
```

Even after a pass, wait for Madis's explicit confirmation that the physical
safety checklist is complete and the vehicle may depart. The driver must never
be asked to troubleshoot or mark events while moving.
