# Deployment

## Controller

```bash
scripts/install-controller.sh
systemctl --user status ltap-testbench-web.service
```

The default web URL is `http://127.0.0.1:8787`.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ltap-testbench db init
ltap-testbench demo seed
ltap-testbench serve
```
