# LtAP LTE Testbench

Linux-hosted benchmark and diagnostics application for MikroTik LtAP dual-LTE routers and generic reference routers.

This repository is the new source of truth for the LTE latency and throughput testbench. The first implementation is intentionally conservative: it can run locally without a router, stores profiles and runs in SQLite, exposes a FastAPI REST/UI surface, provides a CLI, and includes fake/generic adapters so tests can be developed before live hardware is connected.

## Current Status

- Local controller app scaffold: working.
- Generic/fake preflight and simulated run flow: working.
- Test-node profiles, health checks, reservations, and upload-sink accounting: working.
- Stockbot-compatible test-node fileserver deployment: available under `deploy/`.
- RouterOS live changes: not implemented in the MVP and not attempted while the router is disconnected.
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
