# dual-operator LTE7 crossover lte7-elisa-telia-crossover

Updated: 2026-08-11T16:44:45+00:00

RouterOS: `7.24rc3`.
Bands restored: `false`.
SIM swap verified: `true`.

## SIM Map

- Phase A: `{"lte1": {"apn_present": false, "interface": "lte1", "modem": "R11l-LTE7", "modem_id": "MODEM-acff51c319", "modem_label": "LTE7-A", "operator": "telia", "operator_raw": "Telia", "registration_state": "registered", "sim_id": "SIM-b536bd05e0"}, "lte2": {"apn_present": false, "interface": "lte2", "modem": "R11l-LTE7", "modem_id": "MODEM-f467fcf911", "modem_label": "LTE7-B", "operator": "elisa", "operator_raw": "Elisa EE", "registration_state": "registered", "sim_id": "SIM-0464aca4a8"}}`
- Phase B: `{"lte1": {"apn_present": false, "interface": "lte1", "modem": "R11l-LTE7", "modem_id": "MODEM-acff51c319", "modem_label": "LTE7-A", "operator": "elisa", "operator_raw": "Elisa EE", "registration_state": "registered", "sim_id": "SIM-0464aca4a8"}, "lte2": {"apn_present": false, "interface": "lte2", "modem": "R11l-LTE7", "modem_id": "MODEM-f467fcf911", "modem_label": "LTE7-B", "operator": "telia", "operator_raw": "Telia", "registration_state": "registered", "sim_id": "SIM-b536bd05e0"}}`

## Selected Bands

- Selected exact bands: `B3, B7, B20`
- AUTO fallback: `false`

| Item | Phase | Band | Status | LTE1 operator | LTE1 Mbps | LTE1 loss % | LTE1 p95 | LTE2 operator | LTE2 Mbps | LTE2 loss % | LTE2 p95 |
|---|---|---|---|---|---:|---:|---:|---|---:|---:|---:|
| A-B3 | A | 3 | PASS_DUAL | telia | 5.999 | 0 | 32.5 | elisa | 5.982 | 0.279 | 35.5 |
| A-B7 | A | 7 | PASS_DUAL | telia | 5.999 | 0 | 34.8 | elisa | 5.076 | 14.276 | 2309 |
| A-B20 | A | 20 | PASS_DUAL | telia | 5.999 | 0 | 32.8 | elisa | 5.997 | 0.024 | 31.9 |
| A-AUTO | A | AUTO | PASS_DUAL | telia | 5.999 | 0 | 31.7 | elisa | 5.853 | 2.421 | 46.6 |
| B-B3 | B | 3 | PASS_DUAL | elisa | 5.738 | 4.355 | 1745 | telia | 5.999 | 0 | 29.7 |
| B-B7 | B | 7 | PASS_DUAL | elisa | 5.523 | 6.786 | 1992 | telia | 5.999 | 0 | 29.7 |
| B-B20 | B | 20 | PENDING |  |  |  |  |  |  |  |  |
| B-AUTO | B | AUTO | PENDING |  |  |  |  |  |  |  |  |

## Required Answers

1. Which pseudonymous SIM was Elisa? See `SIM_MAP_PUBLIC.json` and Phase B map above.
2. Which pseudonymous SIM was Telia? See `SIM_MAP_PUBLIC.json` and Phase B map above.
3. Which modem initially contained each SIM? See Phase A map above.
4. Was the physical crossover verified correctly? `true`.
5. Which bands were available from Telia? See `TELIA_BAND_DISCOVERY.json`.
6. Which bands were simultaneously comparable with Elisa? See `COMMON_BANDS.json`.
7. Was B3 available from both operators? `true`.
8. On B3, how did LTE7-A perform with Elisa vs Telia? See matrix table.
9. On B3, how did LTE7-B perform with Elisa vs Telia? See matrix table.
10. Does B7 degradation follow operator, LTE7 unit, or path? See final classification.
11. Does B7 specifically follow Elisa? See final classification.
12. Are operator differences explained by different EARFCN/bandwidth/cell parameters? See per-run radio summaries and discovery files.
13. Which exact bands appear best for LTE7-A? See matrix table.
14. Which exact bands appear best for LTE7-B? See matrix table.
15. What happened under AUTO, if AUTO was used? AUTO fallback `false`.
16. Is unrestricted AUTO selection justified for either modem/operator? Final answer pending complete crossover.
17. What should the next experiment be? Pending complete crossover.

## LTE7 Production Questions

- Clean LTE7 bands on Elisa: pending complete crossover.
- Clean LTE7 bands on Telia: pending complete crossover.
- Bands to exclude per operator: pending complete crossover.
- AUTO acceptable for Elisa LTE7: pending AUTO results.
- AUTO acceptable for Telia LTE7: pending AUTO results.
- Use for next production driving test: pending complete crossover.

LTE7_INCONCLUSIVE
