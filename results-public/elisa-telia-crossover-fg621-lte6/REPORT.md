# Elisa/Telia crossover elisa-telia-crossover-fg621-lte6

Updated: 2026-08-10T19:49:13+00:00

RouterOS: `7.24rc3`.
Bands restored: `false`.
SIM swap verified: `false`.

## SIM Map

- Phase A: `{"lte1": {"apn_present": false, "interface": "lte1", "modem": "\"R11e-LTE6\"", "operator": "elisa", "operator_raw": "Elisa EE", "registration_state": "registered", "sim_id": "SIM-0464aca4a8"}, "lte2": {"apn_present": false, "interface": "lte2", "modem": "FG621-EA", "operator": "telia", "operator_raw": "Telia EE", "registration_state": "running", "sim_id": "SIM-b536bd05e0"}}`
- Phase B: `{}`

## Selected Bands

- Selected exact bands: `B3, B7, B20`
- AUTO fallback: `false`

| Item | Phase | Band | Status | LTE1 operator | LTE1 Mbps | LTE1 loss % | LTE1 p95 | LTE2 operator | LTE2 Mbps | LTE2 loss % | LTE2 p95 |
|---|---|---|---|---|---:|---:|---:|---|---:|---:|---:|
| A-B3 | A | 3 | PASS_DUAL | elisa | 5.989 | 0.157 | 34.1 | telia | 5.998 | 0 | 37.8 |
| A-B7 | A | 7 | PENDING |  |  |  |  |  |  |  |  |
| A-B20 | A | 20 | PENDING |  |  |  |  |  |  |  |  |
| B-B3 | B | 3 | PENDING |  |  |  |  |  |  |  |  |
| B-B7 | B | 7 | PENDING |  |  |  |  |  |  |  |  |
| B-B20 | B | 20 | PENDING |  |  |  |  |  |  |  |  |

## Required Answers

1. Which pseudonymous SIM was Elisa? See `SIM_MAP_PUBLIC.json` and Phase B map above.
2. Which pseudonymous SIM was Telia? See `SIM_MAP_PUBLIC.json` and Phase B map above.
3. Which modem initially contained each SIM? See Phase A map above.
4. Was the physical crossover verified correctly? `false`.
5. Which bands were available from Telia? See `TELIA_BAND_DISCOVERY.json`.
6. Which bands were simultaneously comparable with Elisa? See `COMMON_BANDS.json`.
7. Was B3 available from both operators? `true`.
8. On B3, how did R11e perform with Elisa vs Telia? See matrix table.
9. On B3, how did FG621 perform with Elisa vs Telia? See matrix table.
10. Does the FG621 B3 problem follow the modem across operators? See final classification.
11. Does it specifically follow Elisa? See final classification.
12. Are operator differences explained by different EARFCN/bandwidth/cell parameters? See per-run radio summaries and discovery files.
13. Which exact bands appear best for FG621 on Telia? See matrix table.
14. Which exact bands appear best for R11e on Telia? See matrix table.
15. What happened under AUTO, if AUTO was used? AUTO fallback `false`.
16. Is unrestricted AUTO selection justified for either modem/operator? Final answer pending complete crossover.
17. What should the next experiment be? Pending complete crossover.

INCONCLUSIVE_OPERATOR_CROSSOVER
