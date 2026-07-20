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

- TCP upload supports two modes. When `payload_bytes` is set, HTTP PUT is finite-payload and is considered valid when stockbot confirms the bytes it received for the per-path run ID. When `payload_bytes` is omitted, HTTP PUT is a timed stream for `duration_seconds`; stockbot records the partial stream and confirms received bytes, duration, source IP, and Mbit/s.
- UDP upload is currently a controlled sender-side load stage: the controller sends UDP datagrams for the configured duration and bitrate through the per-path public port. It becomes receiver-confirmed when Chateau forwards public UDP `18080`/`18081` to stockbot's UDP listener.
- Traffic stages run all configured LTE paths concurrently. For the R1 profile this means `lte1` and `lte2` upload at the same time during TCP, and `lte1` and `lte2` upload at the same time during UDP.
- Latency is sampled from RouterOS ping output to the configured test-node public host. RouterOS 7.23.2 did not return rows for the attempted `routing-table` ping parameter, so the app records whether the requested routing table was actually used.
- LTE telemetry snapshots come from read-only `/interface/lte/monitor` and `/interface/monitor-traffic` calls before and after traffic.
