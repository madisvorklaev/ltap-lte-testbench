# Sample Comparable LTE Configuration

Create a connected-router sample configuration without starting traffic:

```bash
python -m ltap_testbench.cli create-sample-configuration
```

Machine-readable output:

```bash
python -m ltap_testbench.cli create-sample-configuration --json
```

Useful options:

```bash
python -m ltap_testbench.cli create-sample-configuration \
  --router-slug r1-ltap-live \
  --protocol comparable-v1 \
  --target-valid-runs 3 \
  --max-attempts 5
```

The command is idempotent. It creates or reuses the router profile, stockbot
server profile, structured antenna profile, site, repeatability experiment,
variant, and draft batch. It exits non-zero when blocking validation errors are
present, but it still leaves the created records in place for review.

## Prerequisites

- A router profile, normally `r1-ltap-live`, with a working secret reference.
- RouterOS API access for read-only discovery.
- A `stockbot` server profile, or `LTAP_STOCKBOT_URL` for the default profile.
- The frozen `comparable-v1` benchmark protocol.

The command never writes router configuration. It does not change LTE bands,
APNs, routes, firmware, interfaces, SIM settings, firewall rules, or antenna
settings.

## Discovered Fields

When credentials are available, the MikroTik adapter reads:

- `/system/identity/print`
- `/system/resource/print`
- `/system/routerboard/print`
- `/system/package/print`
- `/interface/lte/print detail`
- `/interface/lte/monitor <interface> once`

The router profile keeps a normalized `metadata_json.paths` list containing path
IDs, LTE interfaces, routing tables, source addresses when configured, expected
public IPs when configured, port ranges, and slot labels when available.

Sensitive modem and SIM identifiers are stored only as salted hashes. Plaintext
IMEI, IMSI, ICCID, serial numbers, API secrets, and bearer tokens are not written
to the sample configuration output.

## Created Records

The supplied antenna is stored as:

- slug: `generic-2db-window-2m`
- manufacturer: `Generic`
- model: `Generic 2 dBi window antenna`
- antenna type: `window-mounted cellular antenna`
- nominal peak gain: `2.0 dBi`
- gain source: `estimated`
- cable type: `unknown`
- cable length: `2.0 m`
- cable loss: `null`
- connector loss: `null`
- mounting: `vehicle window`

Effective installed gain remains `null` because cable and connector losses are
unknown. The nominal 2 dBi value must not be treated as installed system gain.

The sample site is `connected-router-current-location`. Coordinates are not
invented.

The experiment is `Sample dual-LTE repeatability baseline`, with comparison
dimension `general_repeatability`. It is a repeatability baseline, not an
antenna A/B comparison.

The variant is `Current connected-router baseline`. If stable modem or router
identity changes, the command creates a versioned variant instead of mutating the
historical one.

The batch is left in `DRAFT`:

- name: `Sample comparable baseline series`
- target valid runs: `3`
- maximum attempts: `5`
- cooldown: `120` seconds
- retry delay: `300` seconds

## Validation

`ready_to_start=true` only when:

- the connected router profile exists and credentials resolve;
- router identity can be read;
- all configured LTE interfaces exist, are running, and are registered;
- each path has its expected active routing-table/default-route relationship;
- required traffic ports are configured;
- stockbot is reachable and reports a version;
- `comparable-v1` exists and is frozen;
- antenna, site, experiment, variant, and batch links are consistent;
- the batch protocol hash matches the frozen protocol;
- the batch remains `DRAFT`.

Common non-blocking warnings:

- antenna cable loss unknown;
- antenna connector loss unknown;
- effective installed antenna gain unknown;
- physical antenna mapping assumed;
- coordinates not recorded;
- current band/cell may vary between runs;
- three valid runs are insufficient for a firm comparison conclusion.

Blocking errors include missing credentials, router unreachable, missing LTE
path, invalid route table, stockbot unavailable, missing test-node version,
required port missing, protocol missing/not frozen, protocol hash mismatch, or a
variant/batch relationship mismatch.

## Sample Output

```text
Sample comparable LTE configuration created

Router:
 Profile: r1-ltap-live
 Identity: ltap-live
 Board: LtAP LTE6
 RouterOS: 7.16
 RouterBOOT: 7.16

LTE paths:
 lte1: lte1, routing table to-lte1, ports 18080
 lte2: lte2, routing table to-lte2, ports 18081

Antenna:
 Generic 2 dBi window antenna
 Nominal gain: 2.0 dBi (estimated)
 Cable: 2.0 m, type unknown
 Effective installed gain: unknown
 Mapping: assumed; physical verification required

Experiment:
 Sample dual-LTE repeatability baseline

Batch:
 Sample comparable baseline series
 Target valid runs: 3
 Maximum attempts: 5
 Protocol: comparable-v1
 State: DRAFT
 Estimated duration: 945 s/attempt, 1065 s/cycle, 3075 s minimum, 5205 s worst case

Ready to start: NO

Warnings:
 - antenna cable loss unknown
 - antenna connector loss unknown
 - effective installed antenna gain unknown
 - physical antenna mapping assumed
 - coordinates not recorded
 - current band/cell may vary between runs
 - three valid runs are insufficient for a firm comparison conclusion
Blocking errors:
 - test_node_unavailable
```

## Review And Start

Review the generated batch in the UI or API before running it. Confirm the
physical antenna-to-modem and MIMO-port mapping, stockbot reachability, route
tables, port assignments, and site description. Start the DRAFT batch manually
only after validation is clean.

Three valid runs are enough to prove the workflow and catch obvious setup
problems. They are not enough for a strong comparative conclusion. Use larger
counterbalanced batches for firmware, antenna, or modem comparisons.
