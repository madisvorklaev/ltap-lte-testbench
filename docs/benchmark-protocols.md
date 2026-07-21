# Benchmark Protocols

LtAP Testbench separates standard benchmark protocols from exploratory tests.

## Standard Protocols

Standard protocols are frozen workload definitions. A run is comparable only when
its protocol hash, result schema, measurement implementation, environment
snapshot, and integrity checks are compatible.

Current seeded protocols:

- `comparable-v1`: normal firmware, modem, antenna, and historical comparison.
- `video-stability-v1`: long redundant-video stability testing.

Changing any measurement-defining value creates a different protocol hash.

Measurement-defining values include:

- phase order and durations;
- TCP mode, measured window, warm-up, rounds, and stream count;
- UDP bitrate, datagram size, and header version;
- video trace ID, trace version, seed, FPS, bitrate, and duration;
- latency and radio sampling cadence;
- path concurrency;
- result schema and measurement implementation version.

Descriptive values are not part of the protocol hash:

- run ID;
- notes;
- candidate label;
- firmware, modem, or antenna value under comparison.

## Exploratory Tests

Custom lab tests remain available. They are useful for troubleshooting and quick
checks, but are not eligible for standard analytics conclusions by default.

Exploratory runs may be compared only with an exact protocol-hash filter and a
clear warning that they are not part of the frozen benchmark set.
