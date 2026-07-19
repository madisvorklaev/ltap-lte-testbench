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
