# ELMO Experiment 2b Dual Repair Rerun

Updated: 2026-08-14T09:07:07.396+00:00
Classification: INCONCLUSIVE_DUAL_RADIO_VARIABILITY

## Runs

- B_dual_6M_repair: INVALID_SERVER_FAILURE; ports lte1=5201 lte2=5202; skew=0.001s
  - lte1: Mbps=None loss=None% jitter=Nonems ping_avg=48.109ms p50=25.7ms p95=148.0ms p99=650.0ms max=650.484ms ping_loss=14.6667% queue_drop_delta=0 cpu_p95=19.0%
  - lte2: Mbps=4.8293488992114915 loss=19.46613333333333% jitter=2.5106858232416274ms ping_avg=115.246ms p50=121.0ms p95=132.0ms p99=149.0ms max=213.094ms ping_loss=38.4566% queue_drop_delta=37098 cpu_p95=19.0%
  - invalid reasons: LTE1_EXIT_1, LTE1_IPERF_ERROR, LTE1_MISSING_MBPS, LTE1_MISSING_LOST_PERCENT, LTE1_MISSING_JITTER_MS, LTE1_PATH_VERIFY_FAIL_WRONG_LTE
- B_dual_6M_repair_retry1: VALID; ports lte1=5205 lte2=5206; skew=0.001s
  - lte1: Mbps=4.754820288554254 loss=20.6704% jitter=1.758403583082675ms ping_avg=118.065ms p50=123.0ms p95=142.0ms p99=174.0ms max=222.559ms ping_loss=37.1465% queue_drop_delta=37080 cpu_p95=29.0%
  - lte2: Mbps=4.83130901440942 loss=19.435733333333335% jitter=2.276260412404488ms ping_avg=88.364ms p50=120.0ms p95=131.0ms p99=136.0ms max=184.89ms ping_loss=85.5738% queue_drop_delta=37808 cpu_p95=29.0%
- C_dual_6M_repair: VALID; ports lte1=5207 lte2=5208; skew=0.001s
  - lte1: Mbps=4.645626401566865 loss=22.552533333333333% jitter=3.496872795209415ms ping_avg=38.968ms p50=30.1ms p95=81.7ms p99=238.0ms max=389.654ms ping_loss=56.6515% queue_drop_delta=0 cpu_p95=32.0%
  - lte2: Mbps=4.829025453518212 loss=19.498666666666665% jitter=2.307894077284781ms ping_avg=31.996ms p50=28.5ms p95=41.8ms p99=161.0ms max=242.028ms ping_loss=22.9834% queue_drop_delta=0 cpu_p95=32.0%

## Diversity

- B: {"available": true, "both_good": 15, "both_impaired": 299, "longest_both_impaired_seconds": 299, "lte1_impaired_lte2_good": 1, "lte2_impaired_lte1_good": 1, "sampled_seconds": 316}
- C: {"available": true, "both_good": 164, "both_impaired": 5, "longest_both_impaired_seconds": 5, "lte1_impaired_lte2_good": 147, "lte2_impaired_lte1_good": 0, "sampled_seconds": 316}

## Interpretation Boundary

This is receiver-confirmed iPerf, path-bound ping, LTE telemetry, queue telemetry, and RouterOS resource evidence.
It is not production GCC/video frame-age evidence and must not be described as proving displayed video latency is fixed.

Rationale: Latency tails differed under the same 5M cap, but not consistently enough for a narrow CAKE claim: B p95 142.0 ms vs C p95 81.7 ms.