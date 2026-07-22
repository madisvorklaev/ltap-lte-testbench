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

Import legacy CSV files deliberately:

```bash
ltap-testbench runs import-legacy-csv /path/to/lte_upload_*.csv --router demo-generic
```

Imported runs are marked `result_schema_version = 1`,
`comparison_eligible = false`, and excluded from standard comparisons unless a
future explicit legacy-only workflow opts into them. Raw modem identifiers from
CSV files are omitted from the imported summary and environment snapshot.

## Current Live Measurement Semantics

- TCP upload supports two modes. When `payload_bytes` is set, HTTP PUT is finite-payload and is considered valid when stockbot confirms the bytes it received for the per-path run ID. When `payload_bytes` is omitted, HTTP PUT is a timed stream for `duration_seconds`; stockbot records the partial stream and confirms received bytes, duration, source IP, and Mbit/s.
- UDP upload is a receiver-confirmed load stage when a stockbot-compatible test node is configured. The controller sends versioned sequence headers through the per-path public port, stockbot accounts for unique, duplicate, out-of-order, and missing datagrams, and analytics uses delivered receiver rate/loss instead of sender rate. If no receiver records are available, the run is explicitly marked sender-side only.
- UDP video probe traffic uses a deterministic trace seed and shared run token across paths. The receiver reports per-path complete frames plus dual-path union, both-path loss, one-second buckets, and longest both-path outage.
- Traffic stages run all configured LTE paths concurrently. For the R1 profile this means `lte1` and `lte2` upload at the same time during TCP, and `lte1` and `lte2` upload at the same time during UDP.
- Latency is sampled from RouterOS ping output to the configured test-node public host. RouterOS 7.23.2 did not return rows for the attempted `routing-table` ping parameter, so the app records whether the requested routing table was actually used.
- LTE telemetry snapshots come from read-only `/interface/lte/monitor` and `/interface/monitor-traffic` calls before and after traffic.
