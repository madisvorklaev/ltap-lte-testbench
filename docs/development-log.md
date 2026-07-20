# Development Log

## 2026-07-19

- Created local repository scaffold for `ltap-lte-testbench`.
- Added safety-first architecture, CLI/API skeleton, database models, fake/generic adapters, local test-node upload sink, CI, and deployment files.
- Preserved legacy script references under `references/legacy/`.
- Did not contact or modify the router because it is disconnected.
- GitHub repository `madisvorklaev/ltap-lte-testbench` is private and synced.
- Created GitHub milestone tracking issues `#1` through `#9`.
- Began Milestone 1 with explicit run state-transition validation, cancellation entrypoints, and incomplete-run recovery tests.
- Added profile/test-plan validation schemas and tests for duplicate paths, bad port ranges, MikroTik management-host requirements, and duplicate stages.
- Added fake router scenarios for FastTrack-enabled preflight failure, wrong-path verification failure, and RouterOS API timeout.
- Added test-node status and metrics endpoints plus reservation conflict/release and upload-sink tests.
- Added per-run artifact persistence and API/CLI artifact listing.
- Added validated service/API creation paths for router profiles and test plans.
- Added server profile persistence plus controller-side test-node client for health, status, metrics, and reservations.
- Added CLI list/create commands for routers, servers, and test plans using JSON profile files.

## 2026-07-20

- Fixed stale docs that still said GitHub auth was pending.
- Added `server_slug` to test-plan config and worker-side test-node reservation/release around runs.
- Added a versioned stockbot fileserver deployment that preserves the old authenticated upload server and adds test-node API/upload endpoints on the existing listener.
- Added generated Markdown/JSON run reports and a run detail page with artifact links, summary, and event timeline.
