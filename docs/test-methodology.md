# Test Methodology

The new methodology separates these concerns:

- path verification before every performance result;
- idle latency with per-packet RTT, loss, gaps, and distribution;
- single-path TCP capacity;
- controlled loaded-latency sweeps;
- simultaneous dual-link production simulation;
- generic/reference router tests without RouterOS telemetry;
- RouterOS and LTE telemetry as independent time-series data.

Historical curl upload tests remain importable for comparison, but flat CSV is not the canonical schema for new runs.

## Current Live Measurement Semantics

- TCP upload supports two modes. When `payload_bytes` is set, HTTP PUT is finite-payload and is considered valid when stockbot confirms the bytes it received for the per-path run ID. When `payload_bytes` is omitted, HTTP PUT is a timed stream for `duration_seconds`; it records client-side throughput and can be server-confirmed after stockbot's updated partial-stream recorder is deployed.
- UDP upload is currently a controlled sender-side load stage: the controller sends UDP datagrams for the configured duration and bitrate through the per-path public port. It becomes receiver-confirmed when stockbot's UDP listener and public UDP forwarding are active.
- Latency is sampled from RouterOS ping output to the configured test-node public host. RouterOS 7.23.2 did not return rows for the attempted `routing-table` ping parameter, so the app records whether the requested routing table was actually used.
- LTE telemetry snapshots come from read-only `/interface/lte/monitor` and `/interface/monitor-traffic` calls before and after traffic.
