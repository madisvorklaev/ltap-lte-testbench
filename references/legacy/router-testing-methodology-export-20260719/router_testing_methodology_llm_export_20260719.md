# LLM Export: MikroTik LtAP LTE Upload Router Testing

Generated: 2026-07-19 Europe/Tallinn
Workspace: `/home/madis/.openclaw/workspace`
Purpose: explain the current router/LTE testing methodology, scripts, outputs, and known conclusions to another LLM so it can suggest improvements.

## Privacy / Sharing Notes

This export is intended to be LLM-compatible. It summarizes local test data and includes script source, but it does not include raw CSV/JSONL rows containing modem identifiers such as IMEI, IMSI, ICCID, or subscriber number. The live scripts collect those fields because RouterOS exposes them; if sharing raw artifacts externally, redact those columns first.

## What We Are Testing

We are comparing LTE upload behavior of MikroTik LtAP-style routers with two LTE modem paths, generally named `lte1` and `lte2` in RouterOS. The current practical test measures upload throughput through two separate public TCP upload endpoints/ports:

- `lte1_port18080`: upload to `http://81.90.121.7:18080/`, intended to be policy-routed through `lte1` / routing table `to-lte1`.
- `lte2_port18081`: upload to `http://81.90.121.7:18081/`, intended to be policy-routed through `lte2` / routing table `to-lte2`.

Each path uploads a roughly 124 MB local file using `curl --upload-file`. In the normal dual-path test, both uploads start at the same time for each iteration, so the result is closer to simultaneous dual-modem uplink behavior than isolated single-modem capacity.

Primary question so far: whether one router/modem/slot/path is consistently worse, and whether observed problems are caused by RouterOS configuration, FastTrack/policy-routing interaction, RF/antenna placement, modem/card/SIM behavior, LTE band/cell scheduling, or load/bufferbloat.

## Current Test Topology and Assumptions

- Test client is a Linux PC connected to the router under test, usually on the router LAN such as `192.168.88.254` for R1.
- RouterOS API is used on the router under test to collect LTE monitor and interface traffic telemetry.
- Public upload target is `81.90.121.7`, listening on two ports.
- Router mangle/routing rules are expected to route TCP destination port `18080` via `lte1` and destination port `18081` via `lte2`.
- For R1, ordinary non-test traffic was previously being FastTracked, and FastTrack interfered with the policy-routed upload test. Temporary accept rules before the FastTrack rule were added for TCP ports `18080,18081` so those test flows bypass FastTrack.
- Test results are stored under `lte-upload-test/results/<run-tag>/`.

## Current Scripts

### `lte_upload_test.py`

Role: main dual-path upload benchmark. It opens RouterOS API, samples LTE telemetry before/during/after each iteration, starts two `curl` upload processes simultaneously, and writes CSV + JSONL + summary JSON.

Important behavior:

- Requires environment variables: `LTAP_USER`, `LTAP_PASSWORD`, `UPLOAD_USER`, `UPLOAD_PASSWORD`.
- RouterOS API default host is `192.168.199.254`, override with `--router-host`.
- Default LTE interfaces: `lte1,lte2`, override with `--interfaces`.
- Output files:
  - `lte_upload_<run_id>.csv`: primary structured data source.
  - `lte_upload_<run_id>.jsonl`: raw RouterOS samples.
  - `lte_upload_<run_id>_summary.json`: compact curl/run summary.
- Samples phases: `before`, repeated `during`, and `after`.
- Collects upload result fields: HTTP status, curl exit code, total upload time, upload speed bytes/s, upload speed Mbit/s, uploaded byte count.
- Collects LTE fields exposed by RouterOS: operator, access technology, band, cell identifiers, CQI, RI, RSSI, RSRP, RSRQ, SINR, interface traffic rates, drops/errors. Raw identifier fields exist in the CSV schema but should be redacted before external sharing.

```python
#!/usr/bin/env python3
import argparse
import csv
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


CSV_FIELDS = [
    "timestamp_utc",
    "run_id",
    "iteration",
    "phase",
    "path_label",
    "url",
    "file_path",
    "file_size_bytes",
    "curl_exit_code",
    "http_code",
    "upload_time_total_s",
    "upload_speed_bytes_s",
    "upload_speed_mbit_s",
    "upload_size_bytes",
    "interface",
    "sim_comment",
    "status",
    "operator",
    "access_technology",
    "primary_band",
    "current_cellid",
    "enb_id",
    "sector_id",
    "phy_cellid",
    "session_uptime",
    "imei",
    "imsi",
    "iccid",
    "subscriber_number",
    "cqi",
    "ri",
    "rssi",
    "rsrp",
    "rsrq",
    "sinr",
    "rx_bits_per_second",
    "tx_bits_per_second",
    "rx_packets_per_second",
    "tx_packets_per_second",
    "rx_drops_per_second",
    "tx_drops_per_second",
    "tx_queue_drops_per_second",
    "rx_errors_per_second",
    "tx_errors_per_second",
]


class RouterOsApi:
    def __init__(self, host, user, password, port=8728, timeout=10):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.sock = None

    def __enter__(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.command(["/login", f"=name={self.user}", f"=password={self.password}"])
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.sock:
            self.sock.close()

    @staticmethod
    def _encode_len(length):
        if length < 0x80:
            return bytes([length])
        if length < 0x4000:
            return bytes([(length >> 8) | 0x80, length & 0xFF])
        if length < 0x200000:
            return bytes([(length >> 16) | 0xC0, (length >> 8) & 0xFF, length & 0xFF])
        if length < 0x10000000:
            return bytes(
                [
                    (length >> 24) | 0xE0,
                    (length >> 16) & 0xFF,
                    (length >> 8) & 0xFF,
                    length & 0xFF,
                ]
            )
        return bytes(
            [0xF0, (length >> 24) & 0xFF, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF]
        )

    def _decode_len(self):
        first = self.sock.recv(1)
        if not first:
            raise EOFError("RouterOS API closed the connection")
        byte = first[0]
        if (byte & 0x80) == 0:
            return byte
        if (byte & 0xC0) == 0x80:
            return ((byte & ~0xC0) << 8) | self.sock.recv(1)[0]
        if (byte & 0xE0) == 0xC0:
            data = self.sock.recv(2)
            return ((byte & ~0xE0) << 16) | (data[0] << 8) | data[1]
        if (byte & 0xF0) == 0xE0:
            data = self.sock.recv(3)
            return ((byte & ~0xF0) << 24) | (data[0] << 16) | (data[1] << 8) | data[2]
        data = self.sock.recv(4)
        return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

    def _write_word(self, word):
        data = word.encode()
        self.sock.sendall(self._encode_len(len(data)) + data)

    def _read_sentence(self):
        words = []
        while True:
            length = self._decode_len()
            if length == 0:
                return words
            data = b""
            while len(data) < length:
                data += self.sock.recv(length - len(data))
            words.append(data.decode(errors="replace"))

    def command(self, words):
        for word in words:
            self._write_word(word)
        self._write_word("")
        replies = []
        while True:
            sentence = self._read_sentence()
            replies.append(sentence)
            if sentence and sentence[0] in ("!done", "!fatal"):
                if sentence[0] == "!fatal":
                    raise RuntimeError(sentence)
                return replies

    @staticmethod
    def rows(replies):
        parsed = []
        for sentence in replies:
            if not sentence or sentence[0] != "!re":
                continue
            row = {}
            for word in sentence[1:]:
                if word.startswith("="):
                    key, value = word[1:].split("=", 1)
                    row[key] = value
            parsed.append(row)
        return parsed


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collect_interfaces(api, interfaces):
    data = {}
    comments = {}
    for row in api.rows(api.command(["/interface/print", "=detail="])):
        if row.get("name") in interfaces:
            comments[row["name"]] = row.get("comment", "")
    for iface in interfaces:
        lte_rows = api.rows(api.command(["/interface/lte/monitor", f"=numbers={iface}", "=once="]))
        traffic_rows = api.rows(api.command(["/interface/monitor-traffic", f"=interface={iface}", "=once="]))
        lte = lte_rows[0] if lte_rows else {}
        traffic = traffic_rows[0] if traffic_rows else {}
        data[iface] = {"lte": lte, "traffic": traffic, "comment": comments.get(iface, "")}
    return data


def flatten_sample(base, iface, sample):
    lte = sample["lte"]
    traffic = sample["traffic"]
    row = dict.fromkeys(CSV_FIELDS, "")
    row.update(base)
    row.update(
        {
            "interface": iface,
            "sim_comment": sample.get("comment", ""),
            "status": lte.get("status") or lte.get("registration-status", ""),
            "operator": lte.get("current-operator", ""),
            "access_technology": lte.get("access-technology", ""),
            "primary_band": lte.get("primary-band", ""),
            "current_cellid": lte.get("current-cellid", ""),
            "enb_id": lte.get("enb-id", ""),
            "sector_id": lte.get("sector-id", ""),
            "phy_cellid": lte.get("phy-cellid", ""),
            "session_uptime": lte.get("session-uptime", ""),
            "imei": lte.get("imei", ""),
            "imsi": lte.get("imsi", ""),
            "iccid": lte.get("iccid", ""),
            "subscriber_number": lte.get("subscriber-number", ""),
            "cqi": lte.get("cqi", ""),
            "ri": lte.get("ri", ""),
            "rssi": lte.get("rssi", ""),
            "rsrp": lte.get("rsrp", ""),
            "rsrq": lte.get("rsrq", ""),
            "sinr": lte.get("sinr", ""),
            "rx_bits_per_second": traffic.get("rx-bits-per-second", ""),
            "tx_bits_per_second": traffic.get("tx-bits-per-second", ""),
            "rx_packets_per_second": traffic.get("rx-packets-per-second", ""),
            "tx_packets_per_second": traffic.get("tx-packets-per-second", ""),
            "rx_drops_per_second": traffic.get("rx-drops-per-second", ""),
            "tx_drops_per_second": traffic.get("tx-drops-per-second", ""),
            "tx_queue_drops_per_second": traffic.get("tx-queue-drops-per-second", ""),
            "rx_errors_per_second": traffic.get("rx-errors-per-second", ""),
            "tx_errors_per_second": traffic.get("tx-errors-per-second", ""),
        }
    )
    return row


def write_samples(writer, raw_file, run_base, samples):
    timestamp = utc_now()
    for iface, sample in samples.items():
        base = dict(run_base)
        base["timestamp_utc"] = timestamp
        writer.writerow(flatten_sample(base, iface, sample))
        raw_file.write(json.dumps({"timestamp_utc": timestamp, "base": base, "interface": iface, "sample": sample}) + "\n")
    raw_file.flush()


def run_upload(label, file_path, url, user, password, result_path):
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--upload-file",
        str(file_path),
        "--output",
        str(result_path),
        "--write-out",
        json.dumps(
            {
                "http_code": "%{http_code}",
                "time_total": "%{time_total}",
                "speed_upload": "%{speed_upload}",
                "size_upload": "%{size_upload}",
                "remote_ip": "%{remote_ip}",
                "remote_port": "%{remote_port}",
            }
        ),
        url,
    ]
    if user or password:
        cmd[4:4] = ["--basic", "--user", f"{user}:{password}"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def parse_curl_result(proc):
    stdout, stderr = proc.communicate()
    result = {"curl_exit_code": str(proc.returncode), "stderr": stderr.strip()}
    try:
        parsed = json.loads(stdout.strip() or "{}")
        result.update(parsed)
    except json.JSONDecodeError:
        result["stdout"] = stdout.strip()
    return result


def bytes_per_second_to_mbit(value):
    try:
        return f"{float(value) * 8 / 1_000_000:.6f}"
    except (TypeError, ValueError):
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=720)
    parser.add_argument("--sample-seconds", type=int, default=15)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--router-host", default="192.168.199.254")
    parser.add_argument("--router-port", type=int, default=8728)
    parser.add_argument("--run-tag", default="")
    parser.add_argument("--interfaces", default="lte1,lte2")
    parser.add_argument("--file-a", required=True)
    parser.add_argument("--url-a", required=True)
    parser.add_argument("--label-a", default="port18080")
    parser.add_argument("--file-b", required=True)
    parser.add_argument("--url-b", required=True)
    parser.add_argument("--label-b", default="port18081")
    args = parser.parse_args()

    router_user = os.environ["LTAP_USER"]
    router_password = os.environ["LTAP_PASSWORD"]
    upload_user = os.environ["UPLOAD_USER"]
    upload_password = os.environ["UPLOAD_PASSWORD"]
    interfaces = [iface.strip() for iface in args.interfaces.split(",") if iface.strip()]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_tag = "".join(char if char.isalnum() or char in "._-" else "_" for char in args.run_tag.strip())
    run_id = f"{safe_tag}_{timestamp_id}" if safe_tag else timestamp_id
    csv_path = output_dir / f"lte_upload_{run_id}.csv"
    raw_path = output_dir / f"lte_upload_{run_id}.jsonl"
    summary_path = output_dir / f"lte_upload_{run_id}_summary.json"

    pairs = [
        (args.label_a, Path(args.file_a), args.url_a),
        (args.label_b, Path(args.file_b), args.url_b),
    ]

    with csv_path.open("w", newline="") as csv_file, raw_path.open("w") as raw_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        csv_file.flush()
        summaries = []
        for iteration in range(1, args.iterations + 1):
            iteration_started = time.monotonic()
            with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                write_samples(
                    writer,
                    raw_file,
                    {"run_id": run_id, "iteration": iteration, "phase": "before"},
                    collect_interfaces(api, interfaces),
                )
                csv_file.flush()

            processes = []
            for label, file_path, url in pairs:
                result_path = output_dir / f"{run_id}_{iteration}_{label}_response.txt"
                processes.append((label, file_path, url, run_upload(label, file_path, url, upload_user, upload_password, result_path)))

            while any(proc.poll() is None for _, _, _, proc in processes):
                time.sleep(args.sample_seconds)
                with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                    write_samples(
                        writer,
                        raw_file,
                        {"run_id": run_id, "iteration": iteration, "phase": "during"},
                        collect_interfaces(api, interfaces),
                    )
                    csv_file.flush()

            upload_results = []
            for label, file_path, url, proc in processes:
                result = parse_curl_result(proc)
                upload_results.append({"label": label, "file": str(file_path), "url": url, **result})
                with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                    samples = collect_interfaces(api, interfaces)
                base = {
                    "run_id": run_id,
                    "iteration": iteration,
                    "phase": "after",
                    "path_label": label,
                    "url": url,
                    "file_path": str(file_path),
                    "file_size_bytes": file_path.stat().st_size,
                    "curl_exit_code": result.get("curl_exit_code", ""),
                    "http_code": result.get("http_code", ""),
                    "upload_time_total_s": result.get("time_total", ""),
                    "upload_speed_bytes_s": result.get("speed_upload", ""),
                    "upload_speed_mbit_s": bytes_per_second_to_mbit(result.get("speed_upload", "")),
                    "upload_size_bytes": result.get("size_upload", ""),
                }
                write_samples(writer, raw_file, base, samples)
                csv_file.flush()
            csv_file.flush()

            summaries.append({"iteration": iteration, "uploads": upload_results})
            if iteration < args.iterations:
                elapsed = time.monotonic() - iteration_started
                time.sleep(max(0, args.interval_seconds - elapsed))

    summary = {"run_id": run_id, "csv": str(csv_path), "raw_jsonl": str(raw_path), "iterations": summaries}
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```

### `analyze_lte_upload.py`

Role: turns a result CSV into a Markdown report with upload averages and LTE telemetry averages.

Important behavior:

- Groups successful uploads by `path_label`.
- Reports average/median upload Mbit/s, average seconds, HTTP codes.
- Reports per-interface average/max TX Mbit/s, average SINR/RSRP/RSRQ/RSSI/CQI, bands seen, and cells seen.
- CSV remains the primary graphing source; JSONL preserves raw RouterOS samples.

```python
#!/usr/bin/env python3
import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mean(values):
    clean = [value for value in values if value is not None]
    return statistics.mean(clean) if clean else None


def median(values):
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


def fmt(value, digits=2):
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def upload_mbit_s(row):
    value = as_float(row.get("upload_speed_mbit_s"))
    if value is not None:
        return value
    bytes_per_second = as_float(row.get("upload_speed_bytes_s"))
    if bytes_per_second is None:
        return None
    return bytes_per_second * 8 / 1_000_000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    rows = list(csv.DictReader(csv_path.open()))
    uploads = {}
    by_iface = defaultdict(list)
    by_iter = defaultdict(list)

    for row in rows:
        by_iface[row["interface"]].append(row)
        by_iter[row["iteration"]].append(row)
        if row["phase"] == "after" and row["path_label"]:
            key = (row["iteration"], row["path_label"])
            uploads.setdefault(key, row)

    lines = [
        "# LTE Upload Test Report",
        "",
        f"Source CSV: `{csv_path}`",
        f"Rows: {len(rows)}",
        "",
        "## Upload Results",
        "",
        "| Path | Runs | Success | Avg Mbit/s | Median Mbit/s | Avg seconds | HTTP codes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    upload_by_path = defaultdict(list)
    for upload in uploads.values():
        upload_by_path[upload["path_label"]].append(upload)

    for path_label, path_rows in sorted(upload_by_path.items()):
        speeds = [upload_mbit_s(row) for row in path_rows if upload_mbit_s(row) is not None]
        times = [as_float(row["upload_time_total_s"]) for row in path_rows]
        success = sum(1 for row in path_rows if row["curl_exit_code"] == "0" and row["http_code"].startswith("2"))
        codes = ", ".join(sorted({row["http_code"] or "n/a" for row in path_rows}))
        lines.append(
            f"| {path_label} | {len(path_rows)} | {success} | {fmt(mean(speeds), 3)} | {fmt(median(speeds), 3)} | {fmt(mean(times), 1)} | {codes} |"
        )

    lines.extend(
        [
            "",
            "## LTE Interface Telemetry",
            "",
            "| Interface | SIM | Samples | Avg TX Mbit/s | Max TX Mbit/s | Avg SINR | Avg RSRP | Avg RSRQ | Avg RSSI | Avg CQI | Bands seen | Cells seen |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )

    for iface, iface_rows in sorted(by_iface.items()):
        tx = [as_float(row["tx_bits_per_second"]) / 1_000_000 for row in iface_rows if as_float(row["tx_bits_per_second"]) is not None]
        sinr = [as_float(row["sinr"]) for row in iface_rows]
        rsrp = [as_float(row["rsrp"]) for row in iface_rows]
        rsrq = [as_float(row["rsrq"]) for row in iface_rows]
        rssi = [as_float(row["rssi"]) for row in iface_rows]
        cqi = [as_float(row["cqi"]) for row in iface_rows]
        bands = ", ".join(sorted({row["primary_band"] for row in iface_rows if row["primary_band"]}))
        cells = ", ".join(sorted({row["current_cellid"] for row in iface_rows if row["current_cellid"]}))
        sim = next((row["sim_comment"] for row in iface_rows if row["sim_comment"]), "")
        lines.append(
            f"| {iface} | {sim} | {len(iface_rows)} | {fmt(mean(tx), 3)} | {fmt(max(tx) if tx else None, 3)} | {fmt(mean(sinr), 2)} | {fmt(mean(rsrp), 2)} | {fmt(mean(rsrq), 2)} | {fmt(mean(rssi), 2)} | {fmt(mean(cqi), 2)} | {bands} | {cells} |"
        )

    lines.extend(["", "## Notes", ""])
    if len(upload_by_path) >= 2:
        averages = {
            path: mean(
                [
                    upload_mbit_s(row)
                    for row in path_rows
                    if upload_mbit_s(row) is not None
                ]
            )
            for path, path_rows in upload_by_path.items()
        }
        fastest = max((value, path) for path, value in averages.items() if value is not None)
        slowest = min((value, path) for path, value in averages.items() if value is not None)
        if fastest[0] and slowest[0]:
            ratio = fastest[0] / slowest[0]
            lines.append(f"- Fastest average upload path: `{fastest[1]}` at {fmt(fastest[0], 3)} Mbit/s.")
            lines.append(f"- Slowest average upload path: `{slowest[1]}` at {fmt(slowest[0], 3)} Mbit/s.")
            lines.append(f"- Fast/slow average ratio: {fmt(ratio, 2)}x.")
    lines.append("- CSV is the primary graphing source; JSONL keeps raw RouterOS samples for deeper inspection.")

    Path(args.output).write_text("\n".join(lines) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
```

### `lte_single_interface_upload_test.py`

Role: isolation test for one LTE interface at a time. It can enable one interface and disable another, wait for the active interface to reconnect, do uploads through one endpoint, then restore the initial enabled/disabled state.

Why it matters: the current dual-path test measures simultaneous behavior. This single-interface script is useful when we need to separate true per-modem capacity from cross-load, policy-routing, queueing, or cell scheduler interactions.

```python
#!/usr/bin/env python3
import argparse
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

from lte_upload_test import (
    CSV_FIELDS,
    RouterOsApi,
    bytes_per_second_to_mbit,
    collect_interfaces,
    parse_curl_result,
    run_upload,
    write_samples,
)


def api_rows(api, words):
    return api.rows(api.command(words))


def interface_disabled_state(api, interfaces):
    rows = api_rows(api, ["/interface/print", "=detail="])
    state = {}
    for row in rows:
        name = row.get("name")
        if name in interfaces:
            state[name] = row.get("disabled", "false") == "true"
    missing = [iface for iface in interfaces if iface not in state]
    if missing:
        raise RuntimeError(f"Missing interface(s): {', '.join(missing)}")
    return state


def set_interface(api, interface, enabled):
    command = "/interface/enable" if enabled else "/interface/disable"
    api.command([command, f"=numbers={interface}"])


def wait_for_connected(router_host, router_port, user, password, interface, timeout_s):
    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        with RouterOsApi(router_host, user, password, port=router_port) as api:
            rows = api_rows(api, ["/interface/lte/monitor", f"=numbers={interface}", "=once="])
        last = rows[0] if rows else {}
        status = last.get("status") or last.get("registration-status")
        if status in {"connected", "registered"}:
            return last
        time.sleep(5)
    raise TimeoutError(f"{interface} did not connect within {timeout_s}s; last monitor row: {last}")


def router_ping(router_host, router_port, user, password, address):
    with RouterOsApi(router_host, user, password, port=router_port) as api:
        replies = api_rows(api, ["/ping", f"=address={address}", "=count=3"])
    received = sum(1 for row in replies if row.get("time") or row.get("status") == "echo reply")
    return {"address": address, "received": received, "rows": replies}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--router-host", required=True)
    parser.add_argument("--router-port", type=int, default=8728)
    parser.add_argument("--run-tag", required=True)
    parser.add_argument("--active-interface", required=True)
    parser.add_argument("--inactive-interface", required=True)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--sample-seconds", type=int, default=15)
    parser.add_argument("--wait-timeout-seconds", type=int, default=180)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--no-restore", action="store_true")
    args = parser.parse_args()

    router_user = os.environ["LTAP_USER"]
    router_password = os.environ["LTAP_PASSWORD"]
    upload_user = os.environ["UPLOAD_USER"]
    upload_password = os.environ["UPLOAD_PASSWORD"]

    interfaces = [args.active_interface, args.inactive_interface]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_tag = "".join(char if char.isalnum() or char in "._-" else "_" for char in args.run_tag.strip())
    run_id = f"{safe_tag}_{timestamp_id}"
    csv_path = output_dir / f"lte_upload_{run_id}.csv"
    raw_path = output_dir / f"lte_upload_{run_id}.jsonl"
    summary_path = output_dir / f"lte_upload_{run_id}_summary.json"

    initial_state = None
    summary = {
        "run_id": run_id,
        "active_interface": args.active_interface,
        "inactive_interface": args.inactive_interface,
        "csv": str(csv_path),
        "raw_jsonl": str(raw_path),
        "iterations": [],
        "restored": False,
    }

    try:
        with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
            initial_state = interface_disabled_state(api, interfaces)
            print(f"Initial disabled state: {initial_state}", flush=True)
            print(f"Enabling {args.active_interface}, disabling {args.inactive_interface}", flush=True)
            set_interface(api, args.active_interface, True)
            set_interface(api, args.inactive_interface, False)

        print(f"Waiting for {args.active_interface} to connect", flush=True)
        connected = wait_for_connected(
            args.router_host,
            args.router_port,
            router_user,
            router_password,
            args.active_interface,
            args.wait_timeout_seconds,
        )
        print(f"{args.active_interface} connected: {connected.get('current-operator', '')} {connected.get('primary-band', '')}".strip(), flush=True)
        summary["connected_monitor"] = connected
        summary["ping"] = router_ping(args.router_host, args.router_port, router_user, router_password, "1.1.1.1")
        print(f"Router ping 1.1.1.1 replies: {summary['ping']['received']}/3", flush=True)

        file_path = Path(args.file)
        with csv_path.open("w", newline="") as csv_file, raw_path.open("w") as raw_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            csv_file.flush()

            for iteration in range(1, args.iterations + 1):
                print(f"Iteration {iteration}/{args.iterations}: uploading {file_path.name} via {args.label}", flush=True)
                with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                    write_samples(
                        writer,
                        raw_file,
                        {"run_id": run_id, "iteration": iteration, "phase": "before"},
                        collect_interfaces(api, interfaces),
                    )
                    csv_file.flush()

                result_path = output_dir / f"{run_id}_{iteration}_{args.label}_response.txt"
                proc = run_upload(args.label, file_path, args.url, upload_user, upload_password, result_path)

                while proc.poll() is None:
                    time.sleep(args.sample_seconds)
                    with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                        write_samples(
                            writer,
                            raw_file,
                            {"run_id": run_id, "iteration": iteration, "phase": "during"},
                            collect_interfaces(api, interfaces),
                        )
                        csv_file.flush()

                result = parse_curl_result(proc)
                speed = bytes_per_second_to_mbit(result.get("speed_upload", ""))
                print(
                    f"Iteration {iteration}/{args.iterations}: HTTP {result.get('http_code', '')}, "
                    f"{speed or 'n/a'} Mbit/s, {result.get('time_total', '')} s",
                    flush=True,
                )
                with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                    samples = collect_interfaces(api, interfaces)
                base = {
                    "run_id": run_id,
                    "iteration": iteration,
                    "phase": "after",
                    "path_label": args.label,
                    "url": args.url,
                    "file_path": str(file_path),
                    "file_size_bytes": file_path.stat().st_size,
                    "curl_exit_code": result.get("curl_exit_code", ""),
                    "http_code": result.get("http_code", ""),
                    "upload_time_total_s": result.get("time_total", ""),
                    "upload_speed_bytes_s": result.get("speed_upload", ""),
                    "upload_speed_mbit_s": bytes_per_second_to_mbit(result.get("speed_upload", "")),
                    "upload_size_bytes": result.get("size_upload", ""),
                }
                write_samples(writer, raw_file, base, samples)
                csv_file.flush()
                summary["iterations"].append({"iteration": iteration, "upload": result})

    finally:
        if initial_state is not None and not args.no_restore:
            print("Restoring initial interface enabled/disabled state", flush=True)
            with RouterOsApi(args.router_host, router_user, router_password, port=args.router_port) as api:
                for interface, was_disabled in initial_state.items():
                    set_interface(api, interface, not was_disabled)
            summary["restored"] = True
            summary["initial_disabled_state"] = initial_state

        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```

### Shell Wrappers

Role: convenience wrappers for common run patterns.

- `run_immediate_test.sh ROUTER_HOST RUN_TAG`: 30 iterations, no interval, 15-second telemetry samples.
- `run_interval_test.sh ROUTER_HOST RUN_TAG INTERVAL_SECONDS`: 30 iterations with configurable spacing.
- `run_6h_test.sh`: older 30-iteration test with 720-second spacing, total about 6 hours.

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 ROUTER_HOST RUN_TAG" >&2
  exit 2
fi

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_HOST="$1"
RUN_TAG="$2"
RESULTS_DIR="$BASE_DIR/results/$RUN_TAG"
mkdir -p "$RESULTS_DIR"

SUMMARY_JSON="$(
  "$BASE_DIR/lte_upload_test.py" \
    --iterations 30 \
    --interval-seconds 0 \
    --sample-seconds 15 \
    --router-host "$ROUTER_HOST" \
    --run-tag "$RUN_TAG" \
    --output-dir "$RESULTS_DIR" \
    --file-a /home/madis/Downloads/for_upload/Obsidian-1.12.7.AppImage \
    --url-a http://81.90.121.7:18080/ \
    --label-a lte1_port18080 \
    --file-b /home/madis/Downloads/for_upload/balena-etcher_2.1.4_amd64.deb \
    --url-b http://81.90.121.7:18081/ \
    --label-b lte2_port18081
)"

echo "$SUMMARY_JSON"

CSV_PATH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["csv"])' <<<"$SUMMARY_JSON")"
REPORT_PATH="${CSV_PATH%.csv}_report.md"
"$BASE_DIR/analyze_lte_upload.py" "$CSV_PATH" --output "$REPORT_PATH"
```

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 ROUTER_HOST RUN_TAG INTERVAL_SECONDS" >&2
  exit 2
fi

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_HOST="$1"
RUN_TAG="$2"
INTERVAL_SECONDS="$3"
RESULTS_DIR="$BASE_DIR/results/$RUN_TAG"
mkdir -p "$RESULTS_DIR"

SUMMARY_JSON="$(
  "$BASE_DIR/lte_upload_test.py" \
    --iterations 30 \
    --interval-seconds "$INTERVAL_SECONDS" \
    --sample-seconds 15 \
    --router-host "$ROUTER_HOST" \
    --run-tag "$RUN_TAG" \
    --output-dir "$RESULTS_DIR" \
    --file-a /home/madis/Downloads/for_upload/Obsidian-1.12.7.AppImage \
    --url-a http://81.90.121.7:18080/ \
    --label-a lte1_port18080 \
    --file-b /home/madis/Downloads/for_upload/balena-etcher_2.1.4_amd64.deb \
    --url-b http://81.90.121.7:18081/ \
    --label-b lte2_port18081
)"

echo "$SUMMARY_JSON"

CSV_PATH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["csv"])' <<<"$SUMMARY_JSON")"
REPORT_PATH="${CSV_PATH%.csv}_report.md"
"$BASE_DIR/analyze_lte_upload.py" "$CSV_PATH" --output "$REPORT_PATH"
```

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$BASE_DIR/results"
mkdir -p "$RESULTS_DIR"

SUMMARY_JSON="$(
  "$BASE_DIR/lte_upload_test.py" \
    --iterations 30 \
    --interval-seconds 720 \
    --sample-seconds 15 \
    --output-dir "$RESULTS_DIR" \
    --file-a /home/madis/Downloads/for_upload/Obsidian-1.12.7.AppImage \
    --url-a http://81.90.121.7:18080/ \
    --label-a lte1_port18080 \
    --file-b /home/madis/Downloads/for_upload/balena-etcher_2.1.4_amd64.deb \
    --url-b http://81.90.121.7:18081/ \
    --label-b lte2_port18081
)"

echo "$SUMMARY_JSON"

CSV_PATH="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["csv"])' <<<"$SUMMARY_JSON")"
REPORT_PATH="${CSV_PATH%.csv}_report.md"
"$BASE_DIR/analyze_lte_upload.py" "$CSV_PATH" --output "$REPORT_PATH"
```

## Result Schema Summary

CSV fields written by the current scripts:

```text
timestamp_utc, run_id, iteration, phase, path_label, url, file_path,
file_size_bytes, curl_exit_code, http_code, upload_time_total_s,
upload_speed_bytes_s, upload_speed_mbit_s, upload_size_bytes,
interface, sim_comment, status, operator, access_technology, primary_band,
current_cellid, enb_id, sector_id, phy_cellid, session_uptime,
imei, imsi, iccid, subscriber_number,
cqi, ri, rssi, rsrp, rsrq, sinr,
rx_bits_per_second, tx_bits_per_second,
rx_packets_per_second, tx_packets_per_second,
rx_drops_per_second, tx_drops_per_second, tx_queue_drops_per_second,
rx_errors_per_second, tx_errors_per_second
```

Interpretation caveat: because the dual-path script samples both interfaces for every phase, a row with `path_label=lte1_port18080` also has one row for `interface=lte1` and one row for `interface=lte2`. Use `path_label` for upload result grouping and `interface` for radio/traffic telemetry grouping.

## Current / Latest R1 FastTrack-Bypass Result

Source report: `lte-upload-test/results/R1_fasttrack_bypass/lte_upload_R1_fasttrack_bypass_combined_successful_20260716_060903_report.md`

```markdown
# LTE Upload Test Report

Source CSV: `/home/madis/.openclaw/workspace/lte-upload-test/results/R1_fasttrack_bypass/lte_upload_R1_fasttrack_bypass_combined_successful_20260716_060903.csv`
Rows: 266

## Upload Results

| Path | Runs | Success | Avg Mbit/s | Median Mbit/s | Avg seconds | HTTP codes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| lte1_port18080 | 2 | 2 | 14.555 | 14.555 | 76.7 | 201 |
| lte2_port18081 | 2 | 2 | 3.013 | 3.013 | 329.2 | 201 |

## LTE Interface Telemetry

| Interface | SIM | Samples | Avg TX Mbit/s | Max TX Mbit/s | Avg SINR | Avg RSRP | Avg RSRQ | Avg RSSI | Avg CQI | Bands seen | Cells seen |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| lte1 |  | 133 | 2.927 | 24.424 | 6.47 | -90.76 | -11.79 | -60.30 | 5.43 | B1@15Mhz earfcn: 523 phy-cellid: 69, B1@15Mhz earfcn: 523 phy-cellid: 71, B20@10Mhz earfcn: 6200 phy-cellid: 69, B20@10Mhz earfcn: 6200 phy-cellid: 71, B3@15Mhz earfcn: 1875 phy-cellid: 69 | 257028619, 257028629 |
| lte2 |  | 133 | 2.977 | 5.748 | 8.63 | -105.88 | -10.38 | -76.00 | 10.49 | B3@15Mhz earfcn: 1875 phy-cellid: 69 | 257028619 |

## Notes

- Fastest average upload path: `lte1_port18080` at 14.555 Mbit/s.
- Slowest average upload path: `lte2_port18081` at 3.013 Mbit/s.
- Fast/slow average ratio: 4.83x.
- CSV is the primary graphing source; JSONL keeps raw RouterOS samples for deeper inspection.

## Additional Attempt Notes

- Requested two more uploads after the first FastTrack-bypass run.
- One additional full dual-path iteration completed cleanly and is included above as iteration 2.
- The next telemetry-driven run was interrupted by a RouterOS API timeout during sampling. NetworkManager logs show this PC had an R1 DHCP lease on Ethernet `eno1` as `192.168.88.254`, then `eno1` lost carrier at `06:02:24`; after that the PC fell back to home Wi-Fi `Traadita internet` at `192.168.70.190`. A direct retry from that home Wi-Fi connection failed immediately with curl exit `7` on both public ports, so that retry is not counted as an R1 LTE upload result.
- Partial artifacts from the interrupted attempt are retained in this directory under `R1_fasttrack_bypass_more2_20260716_055053*` and `R1_fasttrack_bypass_direct_more1_20260716_060903*`.
```

Key interpretation:

- R1 after FastTrack bypass produced a clean dual-path result, but only 2 successful samples per path before the Ethernet/client link dropped.
- `lte1_port18080`: 14.555 Mbit/s average, strong relative result.
- `lte2_port18081`: 3.013 Mbit/s average, weak result.
- R1 `lte1` had much stronger RSRP but lower average CQI than `lte2`; `lte2` had weaker RSRP but acceptable CQI/SINR.
- This suggests the original R1 failure was at least partly a FastTrack/policy-routing problem, but the remaining R1 `lte2` weakness likely needs RF/antenna/SIM/modem/band/cell isolation.

## Prior Router Comparison Results

Source report: `lte-upload-test/results/lte_upload_four_run_comparison_20260630.md`

```markdown
# LTE Upload Four-Run Comparison

Compared runs:

- R99 indoor: `R99/lte_upload_20260630_011839.csv`
- R3 indoor: `R3_7.6/lte_upload_R3_7.6_20260630_081140.csv`
- R3 outdoor: `R3_7.6_outdoor-antennas/lte_upload_R3_7.6_outdoor-antennas_20260630_195249.csv`
- R99 outdoor: `R99_outdoor-antennas/lte_upload_R99_outdoor-antennas_20260630_213448.csv`

## Upload Results

| Run | Path | Success | Avg Mbit/s | Median Mbit/s | Min | Max | Avg seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R99 indoor | lte1/18080 | 30/30 | 5.860 | 6.022 | 3.013 | 8.849 | 183.7 |
| R99 indoor | lte2/18081 | 30/30 | 11.694 | 10.348 | 7.307 | 19.104 | 93.5 |
| R3 indoor | lte1/18080 | 30/30 | 5.113 | 4.876 | 3.996 | 8.029 | 198.1 |
| R3 indoor | lte2/18081 | 30/30 | 4.370 | 4.312 | 3.800 | 5.639 | 228.7 |
| R3 outdoor | lte1/18080 | 30/30 | 5.702 | 5.793 | 4.452 | 7.048 | 176.2 |
| R3 outdoor | lte2/18081 | 30/30 | 7.996 | 8.097 | 4.177 | 11.437 | 128.4 |
| R99 outdoor | lte1/18080 | 30/30 | 4.191 | 3.999 | 2.770 | 6.424 | 248.2 |
| R99 outdoor | lte2/18081 | 30/30 | 4.792 | 3.711 | 2.747 | 11.822 | 237.8 |

## Combined Average

| Run | lte1 + lte2 avg Mbit/s |
| --- | ---: |
| R99 indoor | 17.554 |
| R3 indoor | 9.483 |
| R3 outdoor | 13.698 |
| R99 outdoor | 8.984 |

## Main Findings

- All four tests completed 30/30 uploads on both paths with HTTP `201`.
- R3 improved meaningfully outdoors: combined average rose from `9.483` to `13.698` Mbit/s, about `+44%`.
- R3's improvement came mostly from LTE2: `4.370` to `7.996` Mbit/s, about `+83%`.
- R99 outdoor was much slower than the earlier R99 indoor/6-hour run: combined average fell from `17.554` to `8.984` Mbit/s, about `-49%`.
- R99 outdoor LTE2 was especially worse than R99 indoor LTE2: `11.694` to `4.792` Mbit/s, about `-59%`.
- Among the two outdoor runs, R3 outdoor was clearly better than R99 outdoor: `13.698` vs `8.984` combined Mbit/s, about `+52%`.

## Caveat

The R99 indoor run was the earlier 6-hour spaced run, while the later R3/R99 outdoor runs were back-to-back. Treat the R99 indoor comparison as practical evidence, not a perfectly controlled same-pattern experiment.
```

Additional remembered run outcomes:

- R99 outdoor early morning, back-to-back: `lte1/18080` 6.983 Mbit/s, `lte2/18081` 10.211 Mbit/s, report `lte-upload-test/results/R99_outdoor-early-morning-b2b/lte_upload_R99_outdoor-early-morning-b2b_20260701_072758_report.md`.
- R3 outdoor night 6-hour run: both paths good, `lte1` about 10.08 Mbit/s and `lte2` about 11.43 Mbit/s from earlier discussion.
- Non-MikroTik reference bounded run: 10/10 successful uploads through current router path to `81.90.121.7:18080`, average 9.583 Mbit/s, report `lte-upload-test/results/reference_non_mikrotik/non_mikrotik_reference_bounded_20260701_002346_report.md`.

Current performance read:

- There is no clear evidence that either `lte1` or `lte2` is inherently worse on every router.
- Earlier R3/R99 runs often had `lte2` faster than `lte1`; R1 after FastTrack bypass flips strongly the other way.
- The observed differences are likely dominated by antenna placement, band/cell selection, modem/SIM behavior, network scheduling/load, RouterOS routing/FastTrack behavior, and maybe physical slot/antenna wiring rather than a universal bad modem path.

## R1 FastTrack / Policy Routing Context

Observed issue:

- R1 upload testing originally stalled or behaved badly.
- RouterOS connection tracking showed ordinary forwarded traffic being FastTracked.
- Policy routing for test ports is done via mangle rules:
  - TCP `dst-port=18080` -> routing mark/table `to-lte1`
  - TCP `dst-port=18081` -> routing mark/table `to-lte2`
- FastTrack can bypass normal firewall/mangle processing for established flows, which can invalidate or disturb policy-routing expectations.

Temporary mitigation applied on 2026-07-16:

- Add accept rules before the default FastTrack rule for TCP test ports `18080,18081`, both destination and source port directions, with comments beginning `OpenClaw TEMP no FastTrack R1 upload...`.
- Verify rules exist before the default FastTrack rule.
- Re-run upload test.

Evidence after mitigation:

- R1 `lte1` improved from stalling to 9.7-19.4 Mbit/s sample-level successful uploads.
- R1 `lte2` remained around 3 Mbit/s.
- This supports FastTrack as a real methodology/configuration bug for the test, but does not explain the remaining `lte2` weakness.

## LtAP Hardware / Slot Symmetry Context

Working understanding from MikroTik LtAP documentation and previous analysis:

- LtAP has two miniPCIe slots and multiple SIM slots.
- The modem positions are not perfectly symmetric from a board-design perspective.
- Top miniPCIe slot supports PCIe + USB 2.0 cards, uses SIM slot #1, and shares USB 2.0 line with the built-in USB port.
- Bottom miniPCIe slot is normally USB 2.0 modem-oriented and uses SIM slot #2/#3 depending on model/configuration.
- For LTE upload speeds of this scale, USB 2.0 itself should not be the bottleneck.
- The asymmetry matters for diagnostics because SIM wiring, card support, slot routing, antenna lead installation, and physical placement can differ, but current performance data does not prove one slot is always inferior.

## Known Methodology Weaknesses

1. Dual simultaneous upload mixes per-modem capacity with scheduler/cross-load effects.
2. Current methodology mainly measures upload throughput, not idle latency, loaded latency, jitter, packet loss, or bufferbloat.
3. Ordinary `ping` from the client/router may not follow the intended LTE path unless forced through the same routing table/interface; ECMP/default-route behavior can make latency measurements ambiguous.
4. The two upload files are different files with similar but not identical sizes. This is probably fine for gross throughput, but not ideal for tightly controlled comparison.
5. Some runs are 6-hour spaced, some are immediate back-to-back; those should not be treated as perfectly equivalent.
6. Cell load and time of day clearly matter. R99 outdoor improved strongly in the early morning compared with evening.
7. RouterOS API timeout or client Ethernet link loss can corrupt a run; interrupted or direct-retry artifacts must be excluded from valid LTE results.
8. LTE metrics are sampled every 15 seconds during uploads, so short band/cell/signal transitions can be missed.
9. CQI/SINR/RSRP/RSRQ are useful but do not fully explain throughput; operator scheduling and retransmissions are not directly measured.
10. Current analysis averages interface telemetry across before/during/after phases together, which can blur loaded vs idle radio behavior.

## Suggested Improvements to Ask ChatGPT About

Ask for a revised methodology that adds:

- Idle latency test per LTE path, explicitly forced through `to-lte1` and `to-lte2` or equivalent RouterOS routing-table/interface selection.
- Loaded latency / bufferbloat test while uploading on the same path.
- Single-interface capacity tests using `lte_single_interface_upload_test.py`, alternating `lte1` and `lte2` with identical file/endpoint where possible.
- Dual simultaneous test kept as a separate “combined practical throughput” test.
- Explicit route verification before each run: show which routing table/interface is used for ports `18080/18081` and for latency probes.
- FastTrack verification before each run: assert test flows bypass FastTrack or disable FastTrack only for marked test flows.
- Identical upload file for both paths, or randomized/symmetric file assignment across iterations.
- Separate aggregation for `before`, `during`, and `after` telemetry.
- More frequent LTE telemetry sampling during short tests, if RouterOS API remains stable.
- Run metadata checklist: router model, RouterOS version, modem model/firmware, SIM/operator/APN, antenna location/orientation, slot/card/SIM mapping, band lock settings, time of day, weather/indoor/outdoor, and client link type.
- Isolation matrix: swap antenna leads first, then SIMs, then modem cards, recording whether the slow/latent behavior follows antenna, SIM, modem card, slot, or stays with the LTE interface/routing path.

## Relevant Skill / Operating Instructions

The local skill used for MikroTik/home network work says to prefer read-only discovery first, preserve access, and avoid RouterOS changes without explicit approval. This matters because some test improvements may require RouterOS firewall/routing changes.

```markdown
---
name: madis-home-network
description: Audit, document, troubleshoot, and safely plan changes for Madis's home MikroTik network. Use when Madis asks about his home VLANs, MikroTik RouterOS devices, CAPsMAN/Wi-Fi roaming, Traadita internet, Traadita aparaadid IoT Wi-Fi, guest Wi-Fi, ESP32/AI-on-edge connectivity, network diagrams, RouterOS scripts, security hardening, or future network penetration/audit work.
---

# Madis Home Network

Use this skill for Madis's home network work. The network is MikroTik-based with VLAN70 trusted/admin, VLAN71 IoT, and VLAN72 guest. Treat it as a real home production network: prefer read-only audit first, preserve access, and never apply RouterOS changes without explicit approval.

## Core Rules

- Do not store credentials in this skill or in generated notes. Ask Madis for credentials when needed.
- Use read-only commands for discovery unless Madis explicitly asks to apply changes.
- Before any RouterOS change, create/export backups and state lockout risk.
- Apply config one device at a time, with a fallback management path.
- Prefer official MikroTik docs for command/property verification before producing scripts.
- When sending output to Telegram, use the `message` tool.

## Known Design Intent

- VLAN70: trusted/admin LAN, `192.168.70.0/24`.
- VLAN71: IoT, `192.168.71.0/24`.
- VLAN72: guest, `192.168.72.0/24`.
- VLAN70 should be able to reach every VLAN.
- Other VLANs should be isolated from VLAN70 and from each other unless explicitly allowed.
- Admin access from VLAN70 is acceptable in this home network.
- `Traadita internet`: trusted Wi-Fi, roaming should be very good.
- `Traadita aparaadid`: IoT Wi-Fi, must favor ESP32/AI-on-edge compatibility over roaming.
- Guest Wi-Fi should be available on Chateau and Elutuba.
- Tehnoruum can be standalone legacy wireless if new CAPsMAN cannot manage it, but its Wi-Fi must land in VLAN71.

## Start Here

1. Read `references/current-architecture.md` for device names, addresses, VLAN roles, and prior findings.
2. For a fresh audit, use `scripts/collect_mikrotik_exports.py` or equivalent read-only SSH exports.
3. For remediation planning, read `references/routeros-workflows.md`.
4. Check prior workspace artifacts if present:
   - `/home/madis/.openclaw/workspace/audits/mikrotik/2026-06-17_2342/`
   - `/home/madis/.openclaw/workspace/audits/mikrotik/current-network-architecture.drawio`
   - `/home/madis/.openclaw/workspace/audits/mikrotik/suggested-fixes/`

## Common Tasks

### Audit Current State

- Identify interfaces and routes from the local machine.
- Discover hosts on VLAN70/VLAN71/VLAN72 where reachable.
- Pull RouterOS exports from MikroTik devices using read-only credentials.
- Compare bridge VLAN tables, bridge ports, Wi-Fi/CAPsMAN, firewall filter/NAT, and `/ip service`.
- Report findings in priority order: lockout risk, VLAN isolation, Wi-Fi correctness, exposed services, stale firmware.

### Create RouterOS Scripts

- Generate per-device `.rsc` files, not one monolithic script.
- Include assumptions at the top of each script.
- Avoid irreversible or broad changes without comments and checks.
- Prefer idempotent patterns with `find`, `:if`, and clear comments.
- Verify command/property names against official MikroTik docs and against the device's export.

### Diagram the Network

- Produce draw.io `.drawio` XML when Madis asks for editable diagrams.
- Show current state separately from target state.
- Include VLANs, MikroTik devices, trunks, access ports, SSIDs, and firewall intent.
- Mark audit issues visually but do not overload the diagram with every port detail.

## Reference Use

- `references/current-architecture.md`: current device inventory and important findings from the June 2026 audit.
- `references/routeros-workflows.md`: safe audit workflow, script-generation checklist, and official documentation links.
- `scripts/collect_mikrotik_exports.py`: reusable read-only export collector; prompts for password and does not save credentials.
```

Relevant current home network architecture reference:

```markdown
# Current Architecture Reference

Snapshot based on the read-only audit done on 2026-06-17/18. Re-audit before relying on this for changes.

## Device Inventory

- Chateau: `192.168.70.254` and `192.168.71.254`, S53UG+M hAP ax, main router, DHCP/DNS, `/interface wifi capsman`, RouterOS `7.22.1`.
- Switch: `192.168.70.253`, CRS326-24G-2S+, bridge VLAN switch, RouterOS `7.22.1`.
- Elutuba: `192.168.70.252`, hAP ax3, new `/interface wifi` CAP managed by Chateau, RouterOS `7.22.1`.
- Tehnoruum: `192.168.70.251`, hAP ac lite, legacy `wireless` package, RouterOS `7.22.1`.

## VLANs

- VLAN70 `vlan70_LAN`: trusted/admin, `192.168.70.0/24`, gateway `192.168.70.254`.
- VLAN71 `vlan71_IoT`: IoT, `192.168.71.0/24`, gateway `192.168.71.254`.
- VLAN72 `vlan72_guest`: guest, `192.168.72.0/24`, gateway `192.168.72.254`.

Design intent:

- VLAN70 may initiate access to VLAN71/VLAN72.
- VLAN71/VLAN72 should not initiate access to VLAN70 or to each other.
- Router administrative access may be open from VLAN70.

## Wi-Fi Intent

- `Traadita internet`: trusted SSID, VLAN70, strong roaming desired. WPA2/WPA3 + FT is acceptable.
- `Traadita aparaadid`: IoT SSID, VLAN71, ESP32/AI-on-edge compatible. Prefer WPA2-PSK only, no FT, 2.4 GHz, 20 MHz.
- `Traadita kylalised`: guest SSID, VLAN72, should be available on Chateau and Elutuba.

## June 2026 Findings

- VLAN filtering was enabled on all MikroTik devices.
- Chateau routed VLAN70/71/72 and ran the new Wi-Fi CAPsMAN.
- Elutuba was correctly managed by Chateau as a new Wi-Fi CAP.
- Tehnoruum used legacy `wireless`; Chateau's new Wi-Fi CAPsMAN does not manage it. Standalone IoT AP on VLAN71 is the pragmatic path unless a legacy CAPsMAN controller is introduced.
- IoT/guest VLAN interfaces were in the router `LAN` interface list, making router input too trusted.
- VLAN72 isolation was incomplete.
- Several trunks/access ports admitted too much traffic:
  - trunks should use `frame-types=admit-only-vlan-tagged` and `ingress-filtering=yes`;
  - access ports should use `frame-types=admit-only-untagged-and-priority-tagged`, correct `pvid`, and `ingress-filtering=yes`.
- Switch VLAN table listed `ether1`/`ether2` as untagged VLAN70 even though export noted they were not bridge ports.
- MikroTik services had broad `address=""` exposure; recommended home compromise is SSH/Winbox/WebFig restricted to `192.168.70.0/24`, with Telnet/FTP/API disabled.
- RouterOS `7.22.1` was behind current stable at the time (`7.23.1` on 2026-06-03).

## Important Prior Artifacts

Workspace paths from the audit:

- Exports: `/home/madis/.openclaw/workspace/audits/mikrotik/2026-06-17_2342/`
- Diagram: `/home/madis/.openclaw/workspace/audits/mikrotik/current-network-architecture.drawio`
- Suggested scripts: `/home/madis/.openclaw/workspace/audits/mikrotik/suggested-fixes/`
- Verified archive: `/home/madis/.openclaw/workspace/audits/mikrotik/suggested-fixes-2026-06-18-verified.tar.gz`

Do not assume these scripts are still correct after time has passed; re-audit first.
```

## Important Local Files

Scripts:

- `lte-upload-test/lte_upload_test.py`
- `lte-upload-test/analyze_lte_upload.py`
- `lte-upload-test/lte_single_interface_upload_test.py`
- `lte-upload-test/run_immediate_test.sh`
- `lte-upload-test/run_interval_test.sh`
- `lte-upload-test/run_6h_test.sh`
- `lte-upload-test/generate_lte_whitepaper.py`

Reports and summaries:

- `lte-upload-test/results/R1_fasttrack_bypass/lte_upload_R1_fasttrack_bypass_combined_successful_20260716_060903_report.md`
- `lte-upload-test/results/lte_upload_four_run_comparison_20260630.md`
- `lte-upload-test/results/R99_outdoor-early-morning-b2b/lte_upload_R99_outdoor-early-morning-b2b_20260701_072758_report.md`
- `lte-upload-test/results/R3_7.6_outdoor-night-6h/lte_upload_R3_7.6_outdoor-night-6h_20260701_005646_report.md`
- `lte-upload-test/results/reference_non_mikrotik/non_mikrotik_reference_bounded_20260701_002346_report.md`
- `lte-upload-test/results/whitepaper/lte_upload_router_comparison_whitepaper_20260701.pdf`

R1 FastTrack-change artifacts:

- `audits/mikrotik/changes/2026-07-16_053222_R1_fasttrack_bypass/prechange_state.json`
- `audits/mikrotik/changes/2026-07-16_053222_R1_fasttrack_bypass/postchange_state.json`
- `audits/mikrotik/changes/2026-07-16_053222_R1_fasttrack_bypass/verification_rules.json`
- `audits/mikrotik/changes/2026-07-16_053222_R1_fasttrack_bypass/post_test_verification.json`

## One-Prompt Version for ChatGPT

You can paste this request into ChatGPT together with this file:

```text
I am testing MikroTik LtAP routers with two LTE modem paths, lte1 and lte2. My current scripts simultaneously upload two ~124 MB files to the same public server on ports 18080 and 18081, with RouterOS mangle/policy routing intended to force 18080 via lte1 and 18081 via lte2. During each iteration I sample RouterOS LTE monitor and interface traffic before, during, and after uploads, then analyze upload Mbit/s and LTE metrics such as RSRP, RSRQ, SINR, CQI, band, and cell.

I have found that FastTrack can break or distort this policy-routed test, so for R1 I temporarily accepted TCP test ports 18080/18081 before the FastTrack rule. After that, R1 lte1 became fast (~14.6 Mbit/s average from two clean samples), while lte2 stayed slow (~3.0 Mbit/s). Previous R3/R99 tests often had lte2 faster, so there is no universal bad modem path. I also know from practical use that R1 lte1 has higher latency than lte2, but we have not measured latency rigorously.

Please review the methodology and scripts in this export. Propose a more rigorous test plan to separate: per-modem capacity, simultaneous dual-uplink performance, idle latency, loaded latency/bufferbloat, FastTrack/routing artifacts, RF/antenna issues, SIM/operator scheduling, band/cell behavior, and physical slot/modem-card differences. I want concrete RouterOS commands or script changes where appropriate, and a clean result schema that supports later comparison across routers.
```
