# LtAP LTE Testbench

Linux-hosted benchmark and diagnostics application for MikroTik LtAP dual-LTE routers and generic reference routers.

This repository is the source of truth for the LTE latency and throughput testbench. It stores router, server, and test-plan profiles in SQLite, exposes a FastAPI REST/UI surface, provides a CLI, and supports both fake/generic development runs and live read-only MikroTik LtAP runs.

## Current Status

- Local controller app scaffold: working.
- Generic/fake preflight and simulated run flow: working.
- Test-node profiles, health checks, reservations, and upload-sink accounting: working.
- Stockbot-compatible test-node fileserver deployment: available under `deploy/`.
- Live LtAP preflight, path verification, latency sampling, TCP uploads, UDP sender-side uploads, LTE telemetry snapshots, and report generation: working.
- RouterOS configuration changes: not implemented and not attempted by the app.
- GitHub remote: private repo synced at `https://github.com/madisvorklaev/ltap-lte-testbench`.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ltap-testbench db init
ltap-testbench demo seed
ltap-testbench serve --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>.

## What The App Can Do Now

- Create/list router, server, and test-plan profiles.
- Run controller and live MikroTik preflight checks.
- Verify configured LTE interfaces and route-table intent.
- Reserve the configured stockbot test node before a run and release it afterward.
- Run finite-payload or timed HTTP/TCP upload tests through per-path public ports.
- Run timed UDP upload tests through the same per-path ports.
- Collect RouterOS LTE snapshots before and after traffic.
- Measure router-originated ping latency to the test node.
- Generate `report.md`, `report.json`, `summary.json`, `events.jsonl`, and plan metadata for each run.
- Show and download reports from the web UI run-detail page.

Finite-payload and timed TCP upload results are server-confirmed by stockbot connection records. UDP results are currently sender-side until Chateau forwards public UDP `18080`/`18081` to stockbot.

## Live R1 LtAP Example

The live router profile is in `deploy/r1-ltap-router-profile.json`. It uses a runtime secret reference:

```json
"secret_ref": "env:LTAP_R1_PASSWORD"
```

Set the password in the shell before CLI runs:

```bash
export LTAP_R1_PASSWORD='<router-password>'
```

For the user systemd web service after a reboot:

```bash
systemctl --user set-environment LTAP_R1_PASSWORD='<router-password>'
systemctl --user restart ltap-testbench-web.service
```

The stockbot profile is in `deploy/stockbot-server-profile.json` and uses the public hairpin endpoint:

```json
{
  "slug": "stockbot",
  "control_api_url": "http://81.90.121.7:18080",
  "public_host": "81.90.121.7"
}
```

The current live smoke plan is in `deploy/r1-live-smoke-plan.json`:

```json
{
  "slug": "r1-live-smoke",
  "server_slug": "stockbot",
  "stages": ["preflight", "path-verification", "idle-latency", "tcp-upload", "udp-upload"],
  "latency": {"duration_seconds": 10, "interval_ms": 1000},
  "tcp_upload": {"duration_seconds": 10, "parallel_streams": [1], "payload_bytes": 1048576},
  "udp_upload": {"duration_seconds": 10, "bitrate_mbit_s": 2.0, "datagram_bytes": 1200}
}
```

To run it from the CLI:

```bash
. .venv/bin/activate
ltap-testbench servers health stockbot --json
ltap-testbench preflight r1-ltap-live --json
ltap-testbench run r1-ltap-live --plan r1-live-smoke --json
ltap-testbench runs list
ltap-testbench runs artifacts <run-id> --json
```

To run it from the web UI:

1. Open <http://127.0.0.1:8787>.
2. Select router `r1-ltap-live`.
3. Select plan `r1-live-smoke`.
4. Click `Run Preflight`.
5. Click `Start Run`.
6. Open the new run and read the inline report or download `report.md` / `report.json`.

## Configuring Test Duration And Load

Create a new plan in the GUI under `Configuration` -> `Create Test Plan`, or use `ltap-testbench plans create <file.json>`.

Example timed plan:

```json
{
  "slug": "r1-60s-upload",
  "name": "R1 60 second upload",
  "server_slug": "stockbot",
  "stages": ["preflight", "path-verification", "idle-latency", "tcp-upload", "udp-upload"],
  "latency": {"duration_seconds": 60, "interval_ms": 1000},
  "tcp_upload": {"duration_seconds": 60, "parallel_streams": [1]},
  "udp_upload": {"duration_seconds": 60, "bitrate_mbit_s": 2.0, "datagram_bytes": 1200},
  "telemetry": {"controller_interval_seconds": 1, "lte_interval_seconds": 5}
}
```

For timed TCP, omit `payload_bytes`; the app streams for `duration_seconds` and reports bytes plus Mbit/s. For finite-payload TCP smoke tests, set `payload_bytes`; the app uploads exactly that many bytes and stockbot confirms received bytes. For UDP, `duration_seconds` and `bitrate_mbit_s` control exactly how long and how fast the sender transmits.

## CLI Examples

```bash
ltap-testbench routers list
ltap-testbench servers list
ltap-testbench preflight demo-generic --json
ltap-testbench run demo-generic --plan quick-check --json
ltap-testbench runs list
```

## Safety

The application defaults to localhost binding, generic/fake test runs, and no RouterOS writes. Any future RouterOS preparation must snapshot first, change only narrowly scoped test state, and restore or produce recovery commands.

Legacy scripts are copied under `references/legacy/` as reference inputs only. They are not automatically safe to execute.
