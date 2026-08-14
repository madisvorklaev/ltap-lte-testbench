# Matched Drive Comparison: CAKE 5M vs PFIFO Reference

Generated UTC: `2026-08-14T20:08:26Z`

PFIFO reference session: `drive-20260812-200856-seedri-smarten-seedri`
CAKE session: `drive-20260814-223317-seedri-smarten-seedri-cake5m-dual6m`

Classification: `INCONCLUSIVE_ROUTE_RADIO_VARIABILITY`

CAKE drive was much worse than the chosen same-route v2 reference on diversity and latency tails, but local artifacts do not prove the reference session queue discipline was PFIFO 5M and the field/radio/GPS conditions differ materially.

## Key Deviation Notes

- The chosen reference drive is the closest completed same-route v2 session, but its local session/report artifacts do not independently record PFIFO 5M queue state.
- Reference drive has 0 valid GPS fixes; CAKE drive has 1613 valid GPS fixes, so geographic alignment is not one-to-one from local artifacts.
- The drives occurred on different days/times, so LTE cell/band choices and RAN load may differ.
- Only route-start was explicitly marked for the CAKE drive; route-end is inferred from stop time.

## Diversity

- PFIFO reference: at least one normal-good path 95.73% ; both impaired 74 s ; longest both-impaired 12 s
- CAKE: at least one normal-good path 8.71% ; both impaired 1739 s ; longest both-impaired 355 s

## Per-Path Metrics

| Condition | Path | Avg Mbps | UDP loss avg % | Ping avg ms | p50 | p95 | p99 | max | ping loss % | >300ms % | longest >300ms s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PFIFO reference | lte1 | 5.588 | 0.421 | 405.363 | 68.4 | 2917.0 | 4956.0 | 5815.0 | 0.178 | 16.013 | 25 |
| PFIFO reference | lte2 | 5.834 | 0.358 | 63.144 | 23.6 | 127.0 | 1286.0 | 2999.0 | 0.204 | 3.769 | 11 |
| CAKE | lte1 | 4.671 | 18.682 | 445.042 | 66.8 | 2461.0 | 6800.0 | 16765.0 | 0.0 | 13.558 | 13 |
| CAKE | lte2 | 4.804 | 18.761 | 49.394 | 28.4 | 94.3 | 572.0 | 3512.0 | 0.0 | 1.511 | 4 |

## Interpretation

Under this run, CAKE did not reproduce the strong field reliability seen in the chosen same-route reference. The CAKE session had far more both-impaired time and worse usable-path diversity.

However, because the local reference artifacts do not prove PFIFO 5M state and because field/radio conditions differ, this should not be presented as a clean one-variable PFIFO-vs-CAKE result. It is best treated as an inconclusive/worse CAKE field attempt that needs a true matched PFIFO/CAKE pair with queue verification embedded in both drive sessions.

This is iPerf/ping queueing evidence, not production video frame-age evidence.
