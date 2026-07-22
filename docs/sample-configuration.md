# Sample Configuration

Create the connected-router sample configuration without starting traffic:

```bash
python -m ltap_testbench.cli create-sample-configuration
```

For machine-readable output:

```bash
python -m ltap_testbench.cli create-sample-configuration --json
```

The command is idempotent. It creates or reuses:

- router profile `r1-ltap-live`;
- antenna profile `generic-2dbi-window`;
- site `current-location`;
- repeatability experiment `Connected router repeatability sample`;
- variant `current connected configuration`;
- draft batch `sample-3-valid-5`.

The batch is created as `DRAFT` with:

- `target_valid_runs = 3`;
- `max_attempts = 5`;
- `inter_run_cooldown_seconds = 120`;
- `retry_delay_seconds = 300`.

The Generic 2 dBi window antenna keeps `effective_gain_dbi = null` because the
2 m cable and connector losses are unknown. Do not treat nominal antenna gain as
installed system gain until those losses are measured or estimated.

The command validates that required records exist and reports readiness, but it
does not start the batch. Start it later from the UI or batch API after checking
the router, test node, antenna mapping, and site are correct.
