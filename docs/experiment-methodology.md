# Experiment Methodology

Comparable LTE tests need both fixed workload and disciplined procedure.

## General Procedure

For each comparison:

1. Use the same frozen protocol.
2. Use the same test node and route validation method.
3. Keep router location, SIMs, APN, and antenna placement controlled unless they
   are the variable under test.
4. Alternate configurations in short blocks where practical.
5. Repeat at least five valid runs per configuration.
6. Keep invalid attempts visible with exclusion reasons.
7. Compare medians, IQR, raw points, and paired deltas rather than single best
   results.

## Firmware

When comparing RouterOS or RouterBOOT, keep router hardware, modems, SIMs,
antennas, site, and protocol constant.

## Modems

Do not treat `lte1` and `lte2` as modem identities. Physical slot, SIM, antenna,
and cable can confound modem results.

Use a crossover when practical:

- modem A in slot 1 and modem B in slot 2;
- then swap modem positions and repeat.

## Antennas

For antenna comparisons, keep firmware, modem, SIM, site, and protocol constant.

Record:

- structured antenna profile;
- cable and connector losses;
- placement and orientation;
- MIMO port mapping;
- path mapping.

Signal quality is an outcome and context field, not just a filter.

## Conclusions

Valid conclusion labels:

- `LIKELY_IMPROVEMENT`;
- `LIKELY_REGRESSION`;
- `INCONCLUSIVE`.

The current analytics implementation reports explicit inconclusive reasons. The
full baseline/candidate confidence engine is still future work.
