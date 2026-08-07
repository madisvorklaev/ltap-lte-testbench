# OpenClaw task: prepare Linux Mint LtAP LTE test workstation

## Objective

Prepare this Linux Mint computer as a repeatable test workstation for several MikroTik LtAP routers with two LTE modems.

The physical antenna/pigtail/router swaps will be done by the user. Your job is to install, configure, verify and maintain the software-side test environment.

The most important goal is **repeatability**, not maximum benchmark speed.

A test must use:
- the same public test server/IP for a campaign;
- the same traffic profile;
- a known LTE1 or LTE2 path;
- continuous LTE/radio telemetry;
- simultaneous latency measurements;
- machine-readable raw results.

Do not silently "fix" a failed test by changing server, modem path, bitrate or duration.

---

## Why public iPerf3 is the primary transport

There is no private upload server available.

Use a public iPerf3 endpoint as the default test transport. iPerf3 supports:
- TCP and UDP;
- a fixed target bitrate for UDP;
- receiver-side UDP loss/jitter;
- JSON output;
- binding the client to a specific local source IP.

This is particularly suitable for the vehicle use case because the actual traffic is a continuous UDP video stream.

A maintained public-server list is available from:
- `https://export.iperf3serverlist.net/listed_iperf3_servers.json`
- project: `https://github.com/R0GGER/public-iperf3-servers`

Public servers are shared infrastructure. Be polite:
- normal campaign tests should be roughly 30–120 seconds;
- use realistic LTE/video rates, not huge artificial rates;
- do not run unattended continuous saturation;
- respect any per-server notes/limits;
- if a server is busy, try another allowed port on the **same pinned host**;
- if the host itself must change, start a new campaign and keep those results separate.

Do **not** make Ookla CLI the default. The currently distributed Ookla CLI package describes its use as personal/non-commercial, which may not fit this project. It may be left as an optional manually enabled comparison tool only if the user confirms the terms are appropriate.

Measurement Lab NDT7 is a possible secondary TCP comparison tool, but M-Lab publishes measurement results including the client public IP. Do not enable it automatically without explaining that to the user.

---

## Files supplied with this handoff

- `ltap_public_test.py` — collector.
- `install_linux_mint.sh` — required Linux packages.
- `setup_test_ips.sh` — temporary two-source-IP setup.
- `config.example.json` — configuration template.
- `routeros_test_routing.rsc.example` — routing concept; never paste it blindly.
- `README.md` — operator instructions.

Treat the Python collector as a functional starter implementation, not untouchable code. You have permission to repair it if live testing reveals RouterOS-version-specific output differences. Preserve raw output whenever a parser is changed.

---

## Expected topology

Typical topology:

```
Linux Mint test PC
   |
   | Ethernet
   |
MikroTik LtAP
   |                  |
  LTE1               LTE2
   |                  |
 mobile network      mobile network
   \                  /
      public iPerf3 server
```

The Linux PC should have two additional source addresses on the same wired interface, for example:

- `192.168.88.201` -> force through LTE1
- `192.168.88.202` -> force through LTE2

The MikroTik should policy-route those source IPs through the already-existing LTE1 and LTE2 routing tables.

The collector runs:

```
iperf3 ... -B 192.168.88.201
```

or

```
iperf3 ... -B 192.168.88.202
```

so test traffic can be selected without depending on the remote server port.

---

# Phase 1 — Inspect, do not change

Before making network changes, inspect the Linux Mint machine.

Record:

```bash
cat /etc/os-release
uname -a
ip -br link
ip -br -4 addr
ip route
nmcli -t -f NAME,UUID,TYPE,DEVICE connection show
```

Identify:
- the wired Ethernet interface physically connected to the LtAP;
- its NetworkManager connection profile;
- current LAN IPv4 address/subnet;
- LtAP management address.

Do not assume `enp3s0` or `192.168.88.1`.

Also verify the attached router:

```bash
ssh <router-user>@<router-ip> '/system/resource/print'
ssh <router-user>@<router-ip> '/interface/lte/print detail'
```

If no SSH key is configured, create a dedicated key and a dedicated RouterOS test user with the minimum policy needed to:
- read system information;
- run `/interface/lte/monitor`;
- read interface statistics;
- run ping if later needed.

Do not store the RouterOS password in source files or shell history.

---

# Phase 2 — Install dependencies

Run:

```bash
chmod +x install_linux_mint.sh
./install_linux_mint.sh
```

Required:
- Python 3
- iperf3
- OpenSSH client
- iproute2
- iputils-ping
- jq
- curl

Verify:

```bash
python3 --version
iperf3 --version
ssh -V
```

---

# Phase 3 — Configure Linux test source IPs

Copy:

```bash
cp config.example.json config.json
```

Edit `config.json` using the real:
- Ethernet interface;
- router address/user/key;
- source IPs;
- RouterOS LTE interface names.

Choose two unused IPs inside the LtAP LAN subnet.

Example only:

```json
"paths": {
  "lte1": {
    "source_ip": "192.168.88.201",
    "lte_interface": "lte1"
  },
  "lte2": {
    "source_ip": "192.168.88.202",
    "lte_interface": "lte2"
  }
}
```

For the first validation, configure them temporarily:

```bash
sudo ./setup_test_ips.sh <ethernet-if> <lte1-ip/cidr> <lte2-ip/cidr>
```

Example:

```bash
sudo ./setup_test_ips.sh enp3s0 192.168.88.201/24 192.168.88.202/24
```

Check:

```bash
ip -4 addr show dev <ethernet-if>
```

Only after everything works, optionally make these addresses persistent in the correct NetworkManager wired profile. Do not change the primary management address or default route unnecessarily.

---

# Phase 4 — Understand the MikroTik routing before editing

This is critical.

Retrieve and save:

```routeros
/export
/routing/table/print detail
/ip/route/print detail
/routing/rule/print detail
/ip/firewall/mangle/print detail
/ip/firewall/nat/print detail
/interface/lte/print detail
```

The routers already have an ELMO configuration that routes traffic by destination port. Reuse the existing LTE-specific routing tables/marks where possible.

The desired additional test behavior is:

```
source=<Linux LTE1 test IP> -> existing LTE1 route/table
source=<Linux LTE2 test IP> -> existing LTE2 route/table
```

Do not assume table names.

Before editing:

```routeros
/export file=before-ltap-test-routing
```

If the router uses mangle `mark-routing`, add two clearly labelled temporary rules matching the Linux source IPs and place them before broader ELMO routing rules.

Use comments:
- `TEMP LTAP TEST LTE1`
- `TEMP LTAP TEST LTE2`

Do not alter modem band configuration as part of workstation setup.

Verify NAT covers both LTE paths.

If existing architecture makes `/routing/rule` safer than mangle, you may use routing rules instead, but document exactly why.

---

# Phase 5 — Prove LTE1/LTE2 path selection

Do not start collecting benchmark data until this is proven.

Run traffic bound to LTE1 source address:

```bash
curl --interface <lte1-source-ip> -4 https://ifconfig.co/ip
```

and LTE2:

```bash
curl --interface <lte2-source-ip> -4 https://ifconfig.co/ip
```

Different public IPs are useful evidence but **not sufficient**, because both mobile sessions may appear behind the same carrier CGNAT address.

The authoritative check is RouterOS interface counters.

Before and during a bound transfer, inspect:

```routeros
/interface/print stats-detail where name="lte1"
/interface/print stats-detail where name="lte2"
```

Traffic from source IP 1 must predominantly increment LTE1.
Traffic from source IP 2 must predominantly increment LTE2.

The supplied collector performs the same basic check after each test and records:
- selected LTE TX/RX byte delta;
- other LTE TX/RX byte delta;
- `path_verification`.

A result that reports `FAIL_OR_COUNTER_PARSE` must not be included in the comparison dataset until resolved.

---

# Phase 6 — Select and PIN a public server

The server is an experimental variable. It must not change silently.

Preferred workflow:

1. Download the current public server export:
   ```bash
   curl -fsSLo /tmp/iperf-servers.json \
     https://export.iperf3serverlist.net/listed_iperf3_servers.json
   ```

2. Inspect the current JSON schema instead of assuming it:
   ```bash
   jq '.[0]' /tmp/iperf-servers.json
   ```

3. Prefer a well-connected server in Northern/Central Europe. Candidates in or near:
   - Estonia
   - Finland
   - Sweden
   - Latvia/Lithuania
   - Germany
   - Netherlands

4. Test candidate availability from **both source IPs** using a 1–2 second TCP test. Do not select a server that works only through one modem.

5. Prefer:
   - same IPv4 endpoint through both modems;
   - stable ports;
   - clearly documented public use;
   - no repeated "server busy";
   - capacity well above LTE rates being measured.

Two examples currently documented by the public server list project are:
- `iperf-ams-nl.eranium.net`
- `ams.speedtest.clouvider.net`

Do not assume they will always be available.

Once selected, initialize the campaign:

```bash
python3 ltap_public_test.py --config config.json campaign-init \
  --server <selected-hostname> \
  --ports 5201 5202 5203 5204 5205 5206 5207 5208 5209 5210 \
  --campaign campaign.json
```

The script resolves the hostname to IPv4 and pins an IP in `campaign.json`.

Review it.

Do not automatically re-resolve on every test.

If the pinned IP/server becomes unavailable:
- stop;
- do not silently fall back;
- create a new `campaign-YYYYMMDD.json`;
- mark subsequent results as a new server campaign.

Using another port on the same pinned server is acceptable when the server provides a pool such as 5201–5210. Record the port, which the collector already does.

---

# Phase 7 — Run collector preflight

```bash
python3 ltap_public_test.py --config config.json preflight \
  --campaign campaign.json
```

It must confirm:
- required commands exist;
- both Linux source IPs are assigned;
- RouterOS SSH works;
- both LTE monitors return parseable fields;
- campaign server exists.

Because the routers have multiple RouterOS versions, especially older 7.x releases, compare a collector sample with interactive RouterOS output:

```routeros
/interface/lte/monitor lte1 once
/interface/lte/monitor lte2 once
```

Make sure fields such as these survive parsing when the modem supports them:
- status
- primary-band
- ca-band
- RSRP
- RSRQ
- SINR
- CQI
- RI
- cell-id / phy-cellid

If older RouterOS output formatting differs:
- fix the parser;
- preserve `lte_raw` in telemetry;
- re-run preflight.

Do not require every modem model to expose every field.

---

# Phase 8 — Standard test profiles

The main vehicle workload is UDP video. Use UDP as the primary test.

## Profile A — realistic video upload

If expected video is about 6 Mbit/s:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol udp \
  --bitrate 6M \
  --packet-length 1200 \
  --duration 120 \
  --tag R0000001_factory_dome_beige
```

Repeat with `--path lte2`.

For physical/config comparisons, use at least three repeats.

## Profile B — headroom staircase

Run:

- 4M
- 6M
- 8M
- 10M
- 12M

Use 60 seconds each initially.

The purpose is to find the sustainable video bitrate where:
- UDP packet loss remains low;
- jitter remains low;
- ping latency does not explode;
- CA/cell state remains stable.

Do not interpret requested UDP bitrate as delivered bitrate; use receiver-side loss/jitter.

## Profile C — TCP saturation / bufferbloat

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol tcp \
  --duration 60 \
  --tag R0000006_FG621_tcp
```

This is specifically useful for investigating the FG621-EA behavior where earlier Ookla tests showed very large latency under upload load.

## Profile D — download

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol tcp \
  --reverse \
  --duration 60 \
  --tag download_check
```

Download is secondary to the vehicle's upload use case.

---

# Phase 9 — Dual-modem test

The final system sends traffic on both LTE modems simultaneously.

Once single-path routing is proven, run two collectors at the same time:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 --protocol udp --bitrate 6M --duration 120 \
  --tag dual_lte1 &

PID1=$!

python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte2 --protocol udp --bitrate 6M --duration 120 \
  --tag dual_lte2 &

PID2=$!

wait "$PID1"
wait "$PID2"
```

Caveat: many public iPerf3 servers accept one client per process/port. The collector may choose different ports from the same server. Confirm both tests actually ran concurrently.

This dual test is especially important for testing band strategies such as:
- both modems automatic;
- both on the same primary band;
- LTE1 B3 + LTE2 B1;
- LTE1 B3 + LTE2 B7;
- LTE1 B1/B7 allowed + LTE2 B3/B20 allowed.

Do not modify band settings automatically. The user will choose/confirm each physical/radio configuration.

---

# Phase 10 — Result format

Every test must create its own timestamped folder.

Preserve:
- `test.json`
- `router_metadata.json`
- `telemetry.jsonl`
- `ping.txt`
- `iperf.json`
- `summary.json`
- stderr files

Append one row to:
- `results/summary.csv`

Do not discard raw telemetry after summary generation.

Important summary fields:
- test tag
- target LTE
- source IP
- pinned server IP + actual port
- UDP target bitrate
- actual throughput
- UDP loss %
- UDP jitter
- TCP retransmits
- ping average/p95/loss
- median RSRP
- median RSRQ
- median SINR
- median CQI
- median RI
- primary bands seen
- CA bands seen
- count of samples with no CA band
- cell changes
- LTE byte deltas
- non-selected LTE byte deltas
- path-verification result

---

# Phase 11 — Improve CA-event analysis

After the basic collector is proven, extend the summary with **state-change events**.

Create `events.jsonl` or an events section in `summary.json` containing timestamps for:
- primary band changed;
- CA band appeared;
- CA band disappeared;
- cell ID changed;
- status changed from connected to another state;
- status returned to connected;
- SINR crossed a configurable low threshold;
- ping timeout burst began/ended.

This is needed to test the observation:

> when the CA band is lost, page loading becomes delayed or fails.

The raw telemetry must make it possible to correlate:
- second of CA loss;
- ping RTT/loss;
- interface throughput;
- iperf interval throughput/loss.

Do not infer causation merely because CA is missing during idle periods.

---

# Phase 12 — Acceptance tests

Do not declare the workstation finished until all of these pass.

## A. Dependency test

```bash
python3 --version
iperf3 --version
ssh -V
```

## B. RouterOS telemetry

For both LTE interfaces:
- status is collected;
- at least RSRP/RSRQ/SINR or equivalent modem data is captured where supported;
- raw output is always retained.

## C. Source route test

Bound LTE1 traffic increments LTE1 counters much more than LTE2.
Bound LTE2 traffic increments LTE2 counters much more than LTE1.

## D. Public server consistency

`campaign.json` contains:
- hostname;
- pinned IPv4;
- allowed port list.

Three consecutive tests use the same server IP.

## E. UDP test

At a conservative 4 Mbit/s:
- test completes;
- JSON parses;
- throughput/loss/jitter summary exists.

## F. TCP test

One 30-second TCP upload test completes and summary exists.

## G. Failure behavior

Temporarily specify an unavailable server/IP and verify:
- collector fails clearly;
- it does NOT switch to another public server silently.

## H. Result isolation

Every run gets a distinct directory and one summary.csv row.

---

# Phase 13 — Git repository

Create a local Git repository for this test tooling.

Suggested structure:

```
ltap-lte-test/
├── README.md
├── OPENCLAW_TASK.md
├── config.example.json
├── .gitignore
├── ltap_public_test.py
├── install_linux_mint.sh
├── setup_test_ips.sh
├── routeros_test_routing.rsc.example
└── docs/
    └── TEST_METHOD.md
```

`.gitignore` must exclude:
- `config.json`
- `campaign*.json`
- `results/`
- SSH keys
- any router exports containing secrets

Do not commit credentials, IMSI, SIM PINs, APN passwords or production secrets.

If a connected GitHub repository is available and the user has already authorized repository creation/publishing for this project, create a private repository and push it. Otherwise keep it local and report the commands needed; do not make a public repository by default.

---

# Important experimental rules

1. Change one variable at a time where practical.
2. Record physical setup in `--tag`.
3. Keep server campaign constant.
4. Do not mix results from different public server campaigns as if they were identical.
5. Prefer 3+ repeats.
6. For moving tests, keep the traffic profile fixed.
7. Save raw LTE telemetry.
8. Do not optimize based only on RSRP.
9. For video, prioritize:
   - packet loss;
   - jitter;
   - loaded latency;
   - disconnections;
   - sustainable throughput.
10. Maximum Speedtest Mbps is secondary.

---

# Final deliverable from OpenClaw

When setup is complete, report to the user:

1. Linux interface used.
2. Linux LTE1/LTE2 source IPs.
3. RouterOS LTE interface names.
4. Existing route-table/mark mapping used for each path.
5. Exact temporary MikroTik rules added.
6. Public iPerf3 server hostname and pinned IPv4.
7. Allowed ports.
8. Results of one LTE1 UDP smoke test.
9. Results of one LTE2 UDP smoke test.
10. Path-verification result for each.
11. Location of the local Git repository.
12. Any RouterOS-version-specific parser fixes made.
13. Exact commands the user should use for:
    - LTE1 test;
    - LTE2 test;
    - dual LTE test.

Do not claim completion if either path-verification test fails.
