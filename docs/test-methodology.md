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
