# Milestones

## Milestone 0: Discovery and Repository

- Local repository scaffold exists.
- Legacy references are preserved.
- Safety docs and assumptions are recorded.
- CI skeleton is present.
- Private GitHub remote is created and synced.

## Milestone 1: Core Models and Fake Environment

- Run state transitions, cancellation, and restart-recovery helpers are covered by tests.
- Profile and test-plan schemas validate path IDs, stage uniqueness, MikroTik host requirements, and port overlap.
- Fake/generic adapters support no-hardware development and simulated failure modes.
- Per-run artifacts are persisted under `var/results/<run-id>/`.
- Server profiles and test-node client support health/status/metrics/reservations.
- Worker-side test-node reservation and release are implemented for plans with `server_slug`.
- Traffic command builders and parsers exist for HTTP upload, iperf3, and IRTT.
- Remaining: Alembic migrations, live traffic stage execution, and separate worker service.

## Next Milestones

2. Raspberry Pi / stockbot test node.
3. Router adapters and preflight.
4. Traffic and telemetry engine.
5. Web UI and OpenClaw API.
6. Reporting and historical import.
7. Safe preparation and configuration generation.
8. Hardening and release.
