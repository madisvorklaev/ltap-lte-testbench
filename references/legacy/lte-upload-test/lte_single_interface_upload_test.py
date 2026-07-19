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
