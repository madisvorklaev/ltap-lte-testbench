# Deployment

## Controller

```bash
scripts/install-controller.sh
systemctl --user status ltap-testbench-web.service
```

The default web URL is `http://127.0.0.1:8787`.

## Stockbot Test Node

Stockbot currently serves the public upload target on `192.168.71.8:8088`. Chateau forwards public ports `18080` and `18081` to this listener. The deployment copy at `deploy/stockbot-fileserver.py` keeps the old authenticated file listing/upload behavior and adds the project test-node API:

- `GET /api/v1/health`
- `GET /api/v1/status`
- `GET /api/v1/metrics`
- `POST /api/v1/reservations`
- `DELETE /api/v1/reservations/{reservation_id}`
- `PUT /upload/{run_id}`
- `GET /api/v1/runs/{run_id}/connections`

This lets the controller reserve stockbot and count upload bytes while old direct `PUT /filename` and browser-form uploads keep working with basic auth.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ltap-testbench db init
ltap-testbench demo seed
ltap-testbench serve
```
