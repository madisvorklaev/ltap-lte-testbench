# Continuation Notes

Last updated: 2026-07-20 Europe/Tallinn.

## Current Local State

- Repository: `/home/madis/projects/ltap-lte-testbench`
- GitHub: `https://github.com/madisvorklaev/ltap-lte-testbench` private
- Branch: `main`
- Last verified pushed commit before 2026-07-20 work: `787d7fe feat: add traffic tool parsers`
- Web service: `ltap-testbench-web.service`
- Local URL: `http://127.0.0.1:8787`
- Database: `var/ltap-testbench.sqlite3` and ignored by Git
- Router state: not contacted; currently disconnected
- Controller network: preflight saw default route on Wi-Fi `wlp2s0` and Ethernet `eno1` down
- GitHub issues: milestone tracking created as issues `#1` through `#9`
- Stockbot upload/test node: `192.168.71.8:8088`, public ports `18080` and `18081` forward to it on `81.90.121.7`.

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
- Runs persist metadata, resolved plan, summary, and events under ignored `var/results/<run-id>/`.
- Runs generate `report.md` and `report.json` artifacts with overview, summary, test-node connection table, and event timeline.
- Router profiles and test plans can be created through validated service/API paths.
- Server profiles exist, with a controller-side test-node client for health/status/metrics/reservations.
- Test plans can reference a `server_slug`; the worker reserves that test node for the run and releases it afterward.
- CLI can list/create routers, servers, and test plans from JSON files; profile list smoke commands passed locally.
- Generic and fake router adapters support safe no-hardware development.
- Controller preflight detects Wi-Fi default route and Ethernet carrier state.
- Legacy upload scripts and methodology export are preserved under `references/legacy/`.
- Test-node upload sink can count and discard uploads, with reservation and health endpoints.
- Stockbot-compatible fileserver deployment is versioned at `deploy/stockbot-fileserver.py`; it preserves the legacy authenticated file server and adds project-compatible test-node endpoints on the same port.
- Dashboard links recent runs to `/runs/{run_id}`, which shows summary JSON, artifact download links, and the event timeline.

## Main Gaps

- MikroTik adapter is read-only scaffold only; secret backend and live discovery are next.
- Worker currently runs synchronously in-process for the MVP.
- IRTT/iperf3/HTTP traffic parsers and command builders exist; live traffic stage execution is still not wired into the run engine.
- SQLite schema is created directly; Alembic migrations are still needed.
- Web UI is a basic dashboard, not the full test wizard.

## Recommended Next Step

Implement Milestone 1:

1. Add Alembic migrations instead of direct `create_all`.
2. Wire the run engine to execute HTTP upload/iperf3/IRTT stages against the reserved test node.
3. Split the worker into a separate service once the durable queue shape is tested.
