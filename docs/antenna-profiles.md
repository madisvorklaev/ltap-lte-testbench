# Antenna Profiles

Standard benchmark series require structured antenna metadata.

Minimum profile fields:

- slug;
- manufacturer and model;
- antenna type;
- MIMO port count;
- gain source;
- nominal peak gain unless gain is unknown;
- cable type and length;
- estimated cable and connector loss when known;
- mounting location;
- orientation.

The useful comparison value is effective installed system gain:

```text
effective gain = nominal antenna gain - cable loss - connector loss
```

The UI and API preserve profile values used by a run in the run environment
snapshot. Historical runs must not change when a profile is edited later.

Unknown gain should be explicit. Runs with unknown gain can still be grouped by
antenna profile, but should not be used for gain-based conclusions.

Path-to-port mapping matters. Future schema work should store which antenna
ports are connected to `lte1` and `lte2`.
