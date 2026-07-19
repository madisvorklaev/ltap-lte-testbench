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
