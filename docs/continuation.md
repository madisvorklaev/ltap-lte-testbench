# Continuation Notes

Last updated: 2026-07-19 Europe/Tallinn.

## Current Local State

- Repository: `/home/madis/projects/ltap-lte-testbench`
- GitHub: `https://github.com/madisvorklaev/ltap-lte-testbench` private
- Branch: `main`
- Last verified feature commit before this note: `c89f387 feat: add test node status and metrics`
- Web service: `ltap-testbench-web.service`
- Local URL: `http://127.0.0.1:8787`
- Database: `var/ltap-testbench.sqlite3` and ignored by Git
- Router state: not contacted; currently disconnected
- Controller network: preflight saw default route on Wi-Fi `wlp2s0` and Ethernet `eno1` down
- GitHub issues: milestone tracking created as issues `#1` through `#9`

## Verification Commands

```bash
cd /home/madis/projects/ltap-lte-testbench
. .venv/bin/activate
ruff check .
ruff format --check .
mypy src testnode/src
pytest
scripts/secret_scan.py .
curl http://127.0.0.1:8787/api/v1/health
```

## What Works

- FastAPI web/API service starts locally.
- CLI can initialize DB, seed demo profiles, list routers, preflight, and run a fake dual-LTE test.
- Run state transitions are validated; cancel and restart-recovery helpers are covered by tests.
- Profile/test-plan schemas validate path IDs, MikroTik host requirements, stage uniqueness, and port overlap.
- Fake adapter can simulate FastTrack-enabled, wrong-path, and API-timeout failures.
- Test-node status/metrics/reservation/upload-sink behavior is covered by tests.
- Generic and fake router adapters support safe no-hardware development.
- Controller preflight detects Wi-Fi default route and Ethernet carrier state.
- Legacy upload scripts and methodology export are preserved under `references/legacy/`.
- Test-node upload sink can count and discard uploads, with reservation and health endpoints.

## Main Gaps

- MikroTik adapter is read-only scaffold only; secret backend and live discovery are next.
- Worker currently runs synchronously in-process for the MVP.
- IRTT/iperf3 traffic stages are not implemented yet.
- SQLite schema is created directly; Alembic migrations are still needed.
- Web UI is a basic dashboard, not the full test wizard.

## Recommended Next Step

Implement Milestone 1:

1. Add Alembic migrations instead of direct `create_all`.
2. Add persisted artifact directories and normalized CSV/JSON writers for simulated runs.
3. Add CLI/API profile creation using the new validation schemas.
4. Split the worker into a separate service once the durable queue shape is tested.
