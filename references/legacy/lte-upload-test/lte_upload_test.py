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
