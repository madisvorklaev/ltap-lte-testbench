# OpenClaw task — prepare the Linux Mint LtAP LTE lab workstation
Version: 1.5

## Scope and starting assumptions

Prepare this Linux Mint PC as a complete, repeatable LTE test workstation.

Assume the MikroTik LtAP has ALREADY been configured with the supplied full RouterOS test script and is physically connected to one of the Linux PC's Ethernet ports.

Do **not** re-import or rewrite the RouterOS configuration unless verification proves that the expected test configuration is missing.

Expected router configuration:

- Router management IP: `192.168.103.254/24`
- LAN bridge/network: `192.168.103.0/24`
- Router DHCP pool: `192.168.103.10-192.168.103.100`
- LTE interfaces: `lte1`, `lte2`
- Routing tables:
  - `to-lte1`
  - `to-lte2`
- MikroTik test policy:
  - source `192.168.103.201/32` -> `to-lte1` -> `lte1`
  - source `192.168.103.202/32` -> `to-lte2` -> `lte2`

Your job is to configure the **Linux PC**, bootstrap authenticated access to the router, install the collector, select/pin a public iPerf3 server, and prove both LTE paths end-to-end.

The physical antenna/pigtail/router swaps will be performed by the user later.

---

# Lab credentials

Credentials were supplied out-of-band for this isolated lab setup and were used
only for local sudo validation and one-time MikroTik SSH-key bootstrap. They are
intentionally not stored in this repository.

- MikroTik username: `admin`

The omitted values are lab secrets.

Rules:

1. You MAY use these credentials without asking the user again.
2. Do not print them in normal status output.
3. Do not commit them to Git.
4. Do not place them in `config.json`, source code, README files, result files, shell history, or Git history.
5. If a temporary secrets file is operationally useful, create it mode `0600`, add it to `.gitignore`, and delete it after SSH-key bootstrap unless still genuinely required.
6. Prefer using the router password only once to bootstrap SSH-key authentication.
7. Do not change the router password.

---

# Primary objective

After setup, the following commands must deterministically test different modems from the same Linux PC:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol udp \
  --bitrate 6M \
  --duration 120 \
  --tag smoke_lte1
```

and:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte2 \
  --protocol udp \
  --bitrate 6M \
  --duration 120 \
  --tag smoke_lte2
```

The Linux source address is the selector:

```text
192.168.103.201 -> Linux policy table ltap-lte1 -> 192.168.103.254
                 -> MikroTik to-lte1 -> lte1

192.168.103.202 -> Linux policy table ltap-lte2 -> 192.168.103.254
                 -> MikroTik to-lte2 -> lte2
```

This must work even if the Linux PC also has Wi-Fi, VPN, or another default Internet route.

---

# Experimental principles

The goal is repeatability, not the highest possible speed-test number.

Each campaign must keep constant:

- public iPerf3 server hostname/IP;
- traffic protocol;
- UDP bitrate when applicable;
- duration;
- packet size;
- test source path;
- telemetry method.

Do not silently change server, path, duration, bitrate, packet size, RouterOS settings, LTE bands, APN, modem firmware, or other variables to make a failed test pass.

Raw results must always be preserved.

---

# Phase 1 — Inspect the Linux machine and identify the LtAP Ethernet port

First record:

```bash
cat /etc/os-release
uname -a
ip -br link
ip -br -4 addr
ip route
ip rule
nmcli -t -f NAME,UUID,TYPE,DEVICE connection show
nmcli -t -f GENERAL.DEVICE,GENERAL.STATE,GENERAL.CONNECTION device show
```

Do not assume the wired interface is `enp3s0`.

Identify the Ethernet interface connected to the LtAP.

Useful methods:

1. Look for an Ethernet interface with carrier.
2. Compare `ip link` before/after unplugging only if necessary.
3. Inspect LLDP/neighbour information if available.
4. Look for DHCP connectivity in `192.168.103.0/24`.
5. Ping `192.168.103.254` from likely wired interfaces.

Do not change unrelated interfaces, Wi-Fi, VPNs, bridges, Docker networks, or virtualization interfaces.

Record the chosen physical interface in a setup report.

Define mentally/in your working state:

```text
LTAP_IF=<actual Linux Ethernet interface>
LTAP_GW=192.168.103.254
MGMT_IP=192.168.103.200/24
LTE1_IP=192.168.103.201/24
LTE2_IP=192.168.103.202/24
```

Before assigning `.200`, `.201`, or `.202`, check for conflicts:

```bash
arping -D -I "$LTAP_IF" 192.168.103.200
arping -D -I "$LTAP_IF" 192.168.103.201
arping -D -I "$LTAP_IF" 192.168.103.202
```

Install `arping` first if necessary.

If any of these addresses are already in use, stop and report the conflict instead of choosing new addresses silently, because the RouterOS policy rules are intentionally tied to `.201` and `.202`.

---

# Phase 2 — Obtain sudo privileges and install dependencies

Use the supplied Linux sudo password when sudo prompts for it.

Do not embed the password in persistent scripts.

Validate sudo:

```bash
sudo -v
```

Install:

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 \
  python3-venv \
  iperf3 \
  openssh-client \
  sshpass \
  iproute2 \
  iputils-ping \
  iputils-arping \
  jq \
  curl \
  git
```

Verify:

```bash
python3 --version
iperf3 --version
ssh -V
ip -Version
nmcli --version
```

`sshpass` is allowed for the one-time lab bootstrap. Do not make the collector depend on it.

---

# Phase 3 — Configure a deterministic Linux Ethernet connection

The Linux PC must have three addresses on the LtAP-facing Ethernet interface:

- `192.168.103.200/24` — ordinary management address
- `192.168.103.201/24` — LTE1 test source
- `192.168.103.202/24` — LTE2 test source

The setup must be persistent across reboot.

## Preferred method: dedicated NetworkManager profile

Find the current NetworkManager connection bound to `LTAP_IF`.

If it is clearly a disposable/default wired profile used only for this lab, modify or replace it.

If it is a user-customized profile with unrelated settings, create a dedicated profile named:

```text
LtAP-Lab
```

The profile should:

- bind to the identified Ethernet interface;
- use static IPv4 addresses `.200`, `.201`, `.202`;
- have no IPv6 dependency for the test;
- avoid becoming the normal system default route when another Internet connection already exists.

A typical NetworkManager configuration is conceptually:

```bash
nmcli con add type ethernet ifname "$LTAP_IF" con-name "LtAP-Lab" \
  ipv4.method manual \
  ipv4.addresses "192.168.103.200/24,192.168.103.201/24,192.168.103.202/24" \
  ipv4.never-default yes \
  ipv6.method disabled
```

If `LtAP-Lab` already exists, update it instead of creating duplicates.

Bring it up:

```bash
nmcli con up "LtAP-Lab"
```

Verify:

```bash
ip -4 addr show dev "$LTAP_IF"
ping -c 3 -I 192.168.103.200 192.168.103.254
```

The connected route for `192.168.103.0/24` must point to `LTAP_IF`.

Do not use `.201` or `.202` as the normal management address.

---

# Phase 4 — Add Linux source-policy routing for LTE1 and LTE2

This is mandatory.

Merely binding iPerf3 to `.201` or `.202` does **not** guarantee that Linux will send public traffic to the LtAP if another default route exists.

Create persistent source-policy tables:

```text
201 ltap-lte1
202 ltap-lte2
```

Prefer a dedicated file:

```text
/etc/iproute2/rt_tables.d/ltap-test.conf
```

with:

```text
201 ltap-lte1
202 ltap-lte2
```

The desired live routing state is:

```bash
ip route replace table ltap-lte1 \
  192.168.103.0/24 dev "$LTAP_IF" src 192.168.103.201

ip route replace table ltap-lte1 \
  default via 192.168.103.254 dev "$LTAP_IF" src 192.168.103.201

ip route replace table ltap-lte2 \
  192.168.103.0/24 dev "$LTAP_IF" src 192.168.103.202

ip route replace table ltap-lte2 \
  default via 192.168.103.254 dev "$LTAP_IF" src 192.168.103.202
```

Create rules with explicit priorities:

```bash
ip rule add priority 20100 from 192.168.103.201/32 lookup ltap-lte1
ip rule add priority 20200 from 192.168.103.202/32 lookup ltap-lte2
```

Make this idempotent: remove or replace previous `ltap-lte1/ltap-lte2` rules instead of accumulating duplicates.

## Persistence

Make the policy routes/rules survive reboot and NetworkManager reconnects.

Preferred implementation:

- `/usr/local/sbin/ltap-test-routing`
- a NetworkManager dispatcher script under `/etc/NetworkManager/dispatcher.d/`
  OR a small systemd oneshot service bound to `network-online.target`

The implementation must:

1. only act on the identified LtAP interface;
2. wait until `.201` and `.202` are assigned;
3. `replace` routes;
4. remove duplicate stale rules before adding the desired priorities;
5. handle interface reconnect cleanly;
6. not modify the PC's other routing tables.

If using a dispatcher, handle both `up` and `down` events appropriately.

After persistence is configured, test it by:

```bash
sudo systemctl restart NetworkManager
```

or by cycling only the `LtAP-Lab` profile.

Then verify again.

---

# Phase 5 — Prove Linux routing before touching the test collector

These commands must resolve to the Ethernet interface and the LtAP gateway:

```bash
ip route get 1.1.1.1 from 192.168.103.201
ip route get 1.1.1.1 from 192.168.103.202
```

Expected conceptually:

```text
1.1.1.1 via 192.168.103.254 dev <LTAP_IF> src 192.168.103.201
1.1.1.1 via 192.168.103.254 dev <LTAP_IF> src 192.168.103.202
```

If either command resolves through Wi-Fi, VPN, another NIC, or another gateway, the workstation is NOT ready.

Also verify router management:

```bash
ping -c 3 -I 192.168.103.200 192.168.103.254
```

---

# Phase 6 — Verify the MikroTik full test configuration

Use the supplied router credentials.

First test password login non-interactively:

```bash
sshpass -p '<router-password>' ssh \
  -o StrictHostKeyChecking=accept-new \
  admin@192.168.103.254 \
  '/system/resource/print'
```

Use the actual supplied password; do not write the literal password into persistent shell scripts.

Then collect:

```routeros
/system/resource/print
/system/routerboard/print
/interface/lte/print detail
/routing/table/print detail
/ip/route/print detail
/ip/firewall/mangle/print detail
/ip/firewall/nat/print detail
/ip/address/print detail
```

Verify specifically:

- `192.168.103.254/24` exists on the LAN;
- both `lte1` and `lte2` exist;
- `to-lte1` and `to-lte2` exist;
- `to-lte1` has a default route via `lte1`;
- `to-lte2` has a default route via `lte2`;
- `.201` has a mark-routing rule to `to-lte1`;
- `.202` has a mark-routing rule to `to-lte2`;
- NAT exists for LTE egress;
- no enabled FastTrack rule can bypass marked test traffic.

Do not change LTE bands, APN, SIM selection, modem firmware, RouterOS version, or radio configuration during workstation setup.

If the expected RouterOS test configuration is missing, stop and report exactly what is absent. Do not invent an alternative router configuration automatically.

---

# Phase 7 — Bootstrap SSH-key access to the MikroTik

The Python collector uses non-interactive SSH and should not store the router password.

Generate a dedicated key if it does not already exist:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -N '' -f ~/.ssh/ltap_test_ed25519
```

Use the supplied router password with `sshpass` only for bootstrap.

Preferred approach:

1. copy the public key to the router file store;
2. import it for the existing `admin` account;
3. prove key authentication;
4. remove the temporary public-key file from the router if appropriate.

Example flow, adapting SCP syntax if RouterOS requires it:

```bash
sshpass -p '<router-password>' scp \
  -o StrictHostKeyChecking=accept-new \
  ~/.ssh/ltap_test_ed25519.pub \
  admin@192.168.103.254:ltap_test_ed25519.pub
```

Then:

```bash
sshpass -p '<router-password>' ssh admin@192.168.103.254 \
  '/user/ssh-keys/import public-key-file=ltap_test_ed25519.pub user=admin'
```

Verify:

```bash
ssh -i ~/.ssh/ltap_test_ed25519 \
  -o BatchMode=yes \
  admin@192.168.103.254 \
  '/system/resource/print'
```

If RouterOS syntax differs on the installed release, inspect `/user/ssh-keys` help and adapt.

Do not change or remove the existing password.

---

# Phase 8 — Install/configure the test collector

Use the supplied:

```text
ltap_public_test.py
```

Create:

```text
config.json
```

from `config.example.json`.

For this lab it should contain, at minimum:

```json
{
  "linux_interface": "<ACTUAL_LTAP_IF>",
  "router": {
    "host": "192.168.103.254",
    "user": "admin",
    "port": 22,
    "ssh_key": "~/.ssh/ltap_test_ed25519"
  },
  "paths": {
    "lte1": {
      "source_ip": "192.168.103.201",
      "lte_interface": "lte1"
    },
    "lte2": {
      "source_ip": "192.168.103.202",
      "lte_interface": "lte2"
    }
  },
  "ping_target": "1.1.1.1"
}
```

Never put the router password or sudo password in `config.json`.

Add to `.gitignore`:

```text
config.json
campaign*.json
results/
lab-secrets*
```

---

# Phase 9 — Validate collector telemetry before network benchmarking

Run:

```bash
python3 ltap_public_test.py --config config.json preflight \
  --campaign campaign.json
```

If a campaign does not yet exist, first initialize one as described below.

Before relying on parser output, compare:

```routeros
/interface/lte/monitor lte1 once
/interface/lte/monitor lte2 once
```

against collector telemetry.

Preserve raw LTE output even if parser changes are needed.

Different modem models may expose different fields.

At minimum, capture where available:

- status;
- primary band;
- CA band;
- RSRP;
- RSRQ;
- SINR;
- CQI;
- RI;
- cell ID / phy-cellid;
- interface byte counters.

---

# Phase 10 — Choose and pin a public iPerf3 server

Use public iPerf3 infrastructure because no reliable private server is available.

Fetch the maintained server export:

```bash
curl -fsSLo /tmp/iperf-servers.json \
  https://export.iperf3serverlist.net/listed_iperf3_servers.json
```

Inspect the current schema:

```bash
jq '.[0]' /tmp/iperf-servers.json
```

Do not hard-code assumptions about the JSON schema without inspecting it.

Prefer a server in Northern or Central Europe, roughly in this order:

- Estonia;
- Finland;
- Sweden;
- Latvia/Lithuania;
- Germany;
- Netherlands.

Candidate requirements:

- reachable through both `.201` and `.202`;
- stable IPv4 address;
- documented public use;
- sufficient capacity;
- no repeated busy/error response;
- preferably multiple iPerf3 ports.

Test candidate reachability separately from both Linux source addresses.

Once chosen, initialize:

```bash
python3 ltap_public_test.py --config config.json campaign-init \
  --server <selected-hostname> \
  --ports 5201 5202 5203 5204 5205 5206 5207 5208 5209 5210 \
  --campaign campaign.json
```

Review `campaign.json`.

The server IP must remain pinned for the campaign.

If the server host itself stops working:

- do not silently select another server;
- end that campaign;
- create a new campaign file;
- keep the result groups distinct.

Changing port on the same server is acceptable if the server explicitly provides multiple public ports and the chosen port is recorded.

Public iPerf3 servers are shared resources:

- use realistic LTE/video rates;
- do not run continuous unattended saturation;
- normal tests should be approximately 30–120 seconds;
- respect server limitations.

---

# Phase 11 — End-to-end LTE path verification

This is an acceptance gate.

The Linux route must be correct AND the MikroTik must actually send each flow through the intended LTE interface.

## LTE1

Before load, note RouterOS counters:

```routeros
/interface/print stats-detail where name="lte1"
/interface/print stats-detail where name="lte2"
```

Generate a short bound flow from:

```text
192.168.103.201
```

Then check counters again.

LTE1 must carry the dominant traffic.

## LTE2

Repeat using:

```text
192.168.103.202
```

LTE2 must carry the dominant traffic.

Do not use public IP alone as proof; carrier CGNAT may obscure the distinction.

The collector's `path_verification` result must also pass.

A failed path verification invalidates the benchmark result.

---

# Phase 12 — Smoke tests

Run conservative smoke tests first.

LTE1:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte1 \
  --protocol udp \
  --bitrate 4M \
  --packet-length 1200 \
  --duration 30 \
  --tag setup_smoke_lte1
```

LTE2:

```bash
python3 ltap_public_test.py --config config.json run \
  --campaign campaign.json \
  --path lte2 \
  --protocol udp \
  --bitrate 4M \
  --packet-length 1200 \
  --duration 30 \
  --tag setup_smoke_lte2
```

Both must:

- complete;
- produce valid iPerf JSON;
- produce LTE telemetry;
- produce ping data;
- produce a `summary.json`;
- append to `results/summary.csv`;
- pass path verification.

If public iPerf server behavior prevents a clean smoke test, try another permitted port on the same pinned server first.

Do not change server host silently.

---

# Phase 13 — Standard test profiles after setup

## A. Realistic video upload

Default:

```text
UDP
6 Mbit/s
1200-byte payload
120 seconds
```

Run both paths separately.

## B. Headroom staircase

Suggested:

```text
4M
6M
8M
10M
12M
```

Initially 60 seconds each.

## C. TCP saturation

Use 30–60 seconds to expose queueing/bufferbloat.

This is particularly relevant to the FG621-EA behavior observed in earlier testing.

## D. Dual-modem

Run LTE1 and LTE2 collectors concurrently at realistic video rates.

Confirm the public server supports simultaneous clients/ports.

---

# Phase 14 — Result integrity

Every run must retain:

- `test.json`
- `router_metadata.json`
- `telemetry.jsonl`
- `ping.txt`
- `iperf.json`
- `summary.json`
- stderr/error files

Append only validated runs to:

```text
results/summary.csv
```

Useful summary dimensions:

- router/test tag;
- source path;
- source IP;
- server IP/port;
- requested bitrate;
- actual throughput;
- UDP loss;
- UDP jitter;
- TCP retransmissions;
- ping average/p95/max/loss;
- RSRP;
- RSRQ;
- SINR;
- CQI;
- RI;
- primary bands;
- CA bands;
- CA missing samples;
- cell changes;
- LTE TX/RX byte deltas;
- non-selected LTE byte deltas;
- path verification.

Raw data must not be discarded.

---

# Phase 15 — CA/cell-state event analysis

After the basic collector is proven, improve it so `summary.json` or
`events.jsonl` records timestamped state changes:

- CA appeared;
- CA disappeared;
- primary band changed;
- cell changed;
- LTE registration/status changed;
- LTE recovered;
- SINR crossed a configurable low threshold;
- ping timeout burst started;
- ping timeout burst ended.

This is needed to test the observation that losing CA sometimes coincides with
page/video stalls.

Do not infer causation merely because CA is absent during idle traffic.

---

# Phase 16 — Git repository

Maintain a local Git repository for the tooling.

Suggested:

```text
ltap-lte-test/
├── README.md
├── OPENCLAW_TASK.md
├── config.example.json
├── .gitignore
├── ltap_public_test.py
├── install_linux_mint.sh
├── docs/
│   ├── TEST_METHOD.md
│   └── LINUX_NETWORK_SETUP.md
└── scripts/
    └── ltap-test-routing
```

Never commit:

- `config.json`
- `campaign*.json`
- `results/`
- credentials
- temporary secrets
- SSH private keys
- RouterOS exports containing secrets
- IMSI/SIM PIN/APN credentials

Do not create a public GitHub repository by default.

---

# Final acceptance criteria

Do not report the workstation as complete until all of the following are true.

## Linux network

- Correct physical Ethernet interface identified.
- `192.168.103.200/24` assigned persistently.
- `192.168.103.201/24` assigned persistently.
- `192.168.103.202/24` assigned persistently.
- `ip route get 1.1.1.1 from 192.168.103.201` uses:
  - LtAP Ethernet interface;
  - gateway `192.168.103.254`;
  - source `.201`.
- Same for `.202`.
- Routing survives connection cycle/reboot setup.

## Router

- `192.168.103.254` reachable.
- SSH key works non-interactively.
- `lte1` and `lte2` exist.
- Both test routing tables exist.
- `.201` maps to LTE1.
- `.202` maps to LTE2.
- LTE interface counters prove actual path selection.

## Collector

- preflight passes;
- telemetry from both LTE interfaces is captured;
- raw RouterOS data retained;
- one LTE1 UDP smoke test passes;
- one LTE2 UDP smoke test passes;
- both have valid path verification;
- `results/summary.csv` is produced.

## Public server

- one public iPerf3 server is pinned;
- its hostname and IPv4 are recorded;
- same server IP used for both smoke tests;
- no silent fallback occurred.

---

# Final report to the user

When finished, report:

1. Linux Mint version.
2. LtAP-facing Linux Ethernet interface.
3. NetworkManager profile name.
4. Management IP used (`192.168.103.200` expected).
5. LTE1 source IP (`192.168.103.201` expected).
6. LTE2 source IP (`192.168.103.202` expected).
7. Exact Linux policy tables/rules created.
8. Results of both `ip route get ... from ...` checks.
9. Router identity/RouterOS version.
10. LTE modem models/firmware if exposed.
11. Public iPerf3 hostname and pinned IPv4.
12. LTE1 smoke-test throughput/loss/jitter/ping/path verification.
13. LTE2 smoke-test throughput/loss/jitter/ping/path verification.
14. Local project/repository path.
15. Any parser or compatibility fixes made.
16. Exact commands the user should use for:
    - LTE1 test;
    - LTE2 test;
    - dual-modem test.

Do not expose the lab passwords in the final report.
