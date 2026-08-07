# LtAP public-server LTE test kit

This kit is meant to be handed to OpenClaw/Codex on a Linux Mint machine.

Start with:

```bash
cat OPENCLAW_TASK.md
```

The intended measurement method is:

**Linux source IP -> MikroTik policy route -> selected LTE modem -> pinned public iPerf3 server**

This gives more repeatable data than letting Ookla choose a different server for every run, and unlike a basic speed test it can generate a controlled UDP bitrate similar to the actual video stream.

## Operator workflow after OpenClaw finishes setup

Typical LTE1 test:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol udp \
  --bitrate 6M \
  --duration 120 \
  --tag R0000001_factory_dome_beige
```

LTE2:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte2 \
  --protocol udp \
  --bitrate 6M \
  --duration 120 \
  --tag R0000001_factory_dome_beige
```

Each run writes raw telemetry and appends one row to `results/summary.csv`.

## Public server warning

Public iPerf3 servers are shared resources and are not under your control. Pin one host/IP for a campaign and do not run excessive unattended saturation. If the server changes, treat subsequent measurements as a new campaign.

See `OPENCLAW_TASK.md` for the full setup and acceptance criteria.
