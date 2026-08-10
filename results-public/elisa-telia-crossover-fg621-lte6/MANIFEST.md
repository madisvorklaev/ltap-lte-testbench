# Manifest elisa-telia-crossover-fg621-lte6

- Purpose: Elisa/Telia SIM crossover across R11e-LTE6 and FG621-EA.
- `lte1` = R11e-LTE6 / V034; `lte2` = FG621-EA / 16121.1034.00.01.01.10.
- Thick beige pigtails, modem slots, antennas, RouterOS and routing remain unchanged.
- Full SIM identifiers are local-only in runtime; public files use pseudonymous SIM IDs.
- Only temporary RouterOS setting changed by the runner: `/interface lte ... band=`.
