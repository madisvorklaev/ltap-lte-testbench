# Continuation Notes

Last updated: 2026-07-22 Europe/Tallinn.

## Current Local State

- Repository: `/home/madis/projects/ltap-lte-testbench`
- GitHub: `https://github.com/madisvorklaev/ltap-lte-testbench` private
- Branch: `main`
- Last verified pushed commit before live throughput work: `9d9da6f feat: add live LtAP smoke test support`
- Web service: `ltap-testbench-web.service`
- Local URL: `http://127.0.0.1:8787`
- Database: `var/ltap-testbench.sqlite3` and ignored by Git
- Router state: connected on the controller LAN at `192.168.101.254`; live RouterOS API preflight works with password resolved from `env:LTAP_R1_PASSWORD`.
- Controller network: default route over `eno1` through the LtAP LAN during live tests.
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
- Runs generate `report.md` and `report.json` artifacts with overview, TCP upload, UDP upload, latency, LTE telemetry, test-node connection, and event timeline sections.
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
- Dashboard command center can seed demo data, run preflight, start runs, check server health, cancel runs, and create router/server/plan records from JSON.
- Live MikroTik read-only preflight/path verification works through RouterOS API credentials resolved from runtime environment secret refs such as `env:LTAP_R1_PASSWORD`.
- Plans with TCP upload stages can run server-confirmed HTTP upload tests to the configured stockbot server and attach test-node connection records to the run summary/report.
- Plans with TCP upload stages can also run stockbot-confirmed timed streams when `tcp_upload.payload_bytes` is omitted.
- Plans with UDP upload stages can run timed UDP uploads through the configured path ports.
- UDP uploads use versioned sequence headers, stockbot receiver accounting, one-second receiver buckets, and server-confirmed delivery/loss metrics when the configured test-node reservation is valid.
- UDP video probe traffic uses a deterministic trace seed, reservation tokens, dual-path receiver union metrics, one-second buckets, both-path loss percentage, and longest both-path outage metrics.
- TCP and UDP stages run all configured LTE paths concurrently.
- Run artifact bundles are downloadable as ZIP files and include protocol, environment, integrity, batch, metric samples, analytics summary, and human-readable reports.
- Live run `run-bcea1fc5bab2` completed against `r1-ltap-live` with latency samples, 1 MiB TCP upload per LTE path, 10 seconds of 2 Mbit/s UDP sender traffic per LTE path, and LTE telemetry snapshots.

## Main Gaps

- MikroTik adapter is read-only but no longer a scaffold; it does not make RouterOS configuration changes.
- Worker currently runs synchronously in-process for the MVP.
- HTTP/TCP upload execution, timed UDP sender execution, RouterOS latency sampling, and LTE telemetry snapshots are wired into the run engine.
- Stockbot now runs the versioned fileserver as user service `stockbot-fileserver.service` from `/home/madis/stockbot-fileserver`; it listens on TCP and UDP `0.0.0.0:8088`.
- Stockbot reservations are enforced on TCP upload, UDP upload, and video traffic; long runs renew reservations and mark runs ineligible if renewal fails.
- IRTT/iperf3 live execution is still pending as a future alternative to the built-in HTTP/UDP stages.
- Alembic migrations are installed for production startup, with legacy SQLite backfill/stamping tests.
- Web UI has command/control coverage but still needs richer guided forms and historical-result import.

## Recommended Next Step

Recommended next step:

1. Continue replacing legacy/live ad hoc measurement paths with phase-aware persisted samples.
2. Add the remaining deep statistical comparison controls and report views.
3. Split the worker into a separate service once the durable queue shape is tested.
