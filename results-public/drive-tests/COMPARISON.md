# Drive Test Comparison

Latest: drive-20260908-190452-auto-dual-6m

See per-session REPORT.md files for quick summaries.

## 2026-09-08 AUTO Dual 6M

`drive-20260908-190452-auto-dual-6m` completed with `V2_CONTINUOUS_TIMELINE` resolution. GPS produced no valid fixes. Both paths were classified impaired for every timeline second under normal and strict criteria, so this run is useful as a failure/impairment case but not as a route-correlated GPS drive.

## CAKE 5M vs PFIFO Reference

See `matched-cake5m-vs-pfifo5m-20260814/REPORT.md`.

Classification: `INCONCLUSIVE_ROUTE_RADIO_VARIABILITY`

CAKE had much worse usable-path diversity than the chosen same-route v2 reference, but the reference session artifacts do not independently prove PFIFO 5M queue state and the field/radio/GPS context differs materially.
