# Manifest lte7-elisa-telia-crossover

- Purpose: Elisa/Telia SIM crossover across two fixed R11l-LTE7 modems.
- `lte1` = LTE7-A; `lte2` = LTE7-B. Public modem IDs are in `MODEM_MAP_PUBLIC.json`.
- Thick beige pigtails, modem slots, antennas, RouterOS and routing remain unchanged.
- Full SIM identifiers are local-only in runtime; public files use pseudonymous SIM IDs.
- Only temporary RouterOS setting changed by the runner: `/interface lte ... band=`.
