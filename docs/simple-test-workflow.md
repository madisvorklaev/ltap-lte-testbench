# Simple Test Workflow

The normal dashboard uses three terms:

- **Test profile**: a fixed, versioned measurement recipe.
- **Test campaign**: a series of repeated runs using one test profile.
- **Run**: one complete execution of the profile.

Measurement properties are fixed inside frozen benchmark protocols. The browser
chooses a profile and campaign target; it does not send bitrate, FPS, packet
size, TCP, UDP, recovery, sampler, or protocol-hash settings in simple mode.

## Profiles

The initial profile list is intentionally short.

`Video Stability — City, 5 Mbps, 25 fps` is the default. Each valid run streams
30 minutes of dual-LTE city video traffic. Six streamed hours becomes twelve
complete 30-minute runs.

`Full Comparable Benchmark` runs the complete comparable protocol: idle latency,
TCP warm-up and measured rounds, UDP delivery, recovery periods, deterministic
video, and final recovery.

`Quick Connection Check` is diagnostic only. Its results are excluded from
comparison analytics.

## Streamed Time And Wall-Clock Time

Target streamed time counts only active video transmission. Wall-clock time also
includes stabilization, idle baseline, receiver settle, final recovery, and
cooldown between runs.

For the default video profile:

```text
30 minutes streamed video per run
34 minutes 5 seconds estimated wall-clock time per successful run
```

For a six-hour target:

```text
6 h streamed time / 30 min per run = 12 valid runs
12 x 2045 s + 11 x 120 s cooldown = 7 h 11 min wall-clock minimum
```

If the requested streamed time is not divisible by the fixed run duration, the
system rounds up to complete runs. It never shortens the final comparable run.

## Campaigns

The preview endpoint derives:

- target valid runs;
- maximum attempts;
- planned streamed time;
- successful-run wall-clock time;
- minimum campaign wall-clock time;
- worst-case campaign wall-clock time;
- validation warnings and blocking errors.

Campaigns remain `DRAFT` until explicitly started, or `SCHEDULED` when a start
time is supplied. Existing test-batch APIs remain available for advanced use.

## Advanced Exploratory Testing

Detailed measurement controls live under `Advanced / exploratory tests`.
Changing measurement properties creates exploratory results unless a new frozen,
versioned profile is created.

When measurement semantics change, create a new benchmark protocol/profile
version. Retire the old profile only for new campaigns; existing campaigns keep
their stored profile snapshot and protocol hash.
