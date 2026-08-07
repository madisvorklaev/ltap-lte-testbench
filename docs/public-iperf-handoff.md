# Public iPerf3 Handoff

The Telegram handoff from 2026-08-07 is preserved under
`references/public-iperf-kit/`.

That kit is a standalone Linux Mint collector for campaigns that use a pinned
public iPerf3 server instead of the private stockbot test node. Keep these
results separate from normal `ltap-testbench` app results unless the server,
traffic profile, path verification, and result schema are explicitly accounted
for.

Use public iPerf3 only as a controlled campaign transport:

- pin one hostname and resolved IPv4 in `campaign.json`;
- keep the same allowed port list for the campaign;
- bind traffic to the Linux source IP for the intended LTE path;
- prove path selection from RouterOS LTE byte counters before using results;
- preserve raw `telemetry.jsonl`, `iperf.json`, `ping.txt`, and stderr files;
- start a new campaign file if the pinned host/IP changes.

The current app remains the source of truth for stockbot-confirmed benchmark
campaigns. The public-iPerf kit is reference tooling for cases where no private
upload server is available.

Current local workstation inspection from the handoff turn:

- OS: Linux Mint 22.1.
- Kernel: `6.8.0-136-generic`.
- Active network: Wi-Fi `wlp2s0`, `192.168.70.190/24`.
- Ethernet candidate for LtAP: `eno1`, currently `DOWN`/no carrier.
- Missing package at inspection time: `iperf3`.
- `sudo -n apt-get update` failed because a password is required.

Live acceptance tests are therefore still pending until the LtAP is connected
to Ethernet and dependencies are installed interactively.
