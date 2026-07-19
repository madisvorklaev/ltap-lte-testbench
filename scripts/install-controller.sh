#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ltap-testbench db init
ltap-testbench demo seed

mkdir -p "$HOME/.config/systemd/user"
sed "s#__ROOT__#$ROOT#g" deploy/ltap-testbench-web.service.in > "$HOME/.config/systemd/user/ltap-testbench-web.service"
systemctl --user daemon-reload

echo "Installed. Start with: systemctl --user start ltap-testbench-web.service"
