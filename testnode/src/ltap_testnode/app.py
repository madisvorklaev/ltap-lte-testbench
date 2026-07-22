import time
from datetime import UTC, datetime
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from ltap_testnode.metrics import collect_metrics

app = FastAPI(title="LtAP Test Node")
RUNS: dict[str, list[dict]] = {}
RESERVATIONS: dict[str, dict] = {}
STARTED_AT = time.time()
TEST_NODE_VERSION = "ltap-testnode-0.1"
MEASUREMENT_IMPLEMENTATION_VERSION = "ltap-testnode-measurement-v1"
CAPABILITY_SCHEMA_VERSION = "1"


class ReservationCreate(BaseModel):
    owner: str
    run_id: str | None = None
    ttl_seconds: int = 3600


class ReservationRenew(BaseModel):
    ttl_seconds: int | None = None


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def prune_expired_reservations() -> None:
    now = time.time()
    expired = [
        reservation_id
        for reservation_id, reservation in RESERVATIONS.items()
        if now - reservation["created_epoch"] > reservation["ttl_seconds"]
    ]
    for reservation_id in expired:
        RESERVATIONS.pop(reservation_id, None)


def public_reservation(reservation: dict) -> dict:
    return {key: value for key, value in reservation.items() if key != "token"}


def run_matches_reservation(reserved_run_id: str | None, traffic_run_id: str) -> bool:
    if not reserved_run_id:
        return True
    return traffic_run_id == reserved_run_id or traffic_run_id.startswith(f"{reserved_run_id}-")


def require_reservation(run_id: str, token: str | None) -> None:
    prune_expired_reservations()
    if not token:
        raise HTTPException(status_code=401, detail="missing reservation token")
    for reservation in RESERVATIONS.values():
        if reservation.get("token") != token:
            continue
        if not run_matches_reservation(reservation.get("run_id"), run_id):
            raise HTTPException(status_code=403, detail="reservation run mismatch")
        return
    raise HTTPException(status_code=403, detail="invalid reservation token")


@app.get("/api/v1/health")
def health() -> dict:
    return {
        "ok": True,
        "utc": now_iso(),
        "service": "ltap-testnode",
        "version": TEST_NODE_VERSION,
        "measurement_implementation_version": MEASUREMENT_IMPLEMENTATION_VERSION,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
    }


@app.get("/api/v1/status")
def status() -> dict:
    prune_expired_reservations()
    return {
        "ok": True,
        "utc": now_iso(),
        "started_at_epoch": STARTED_AT,
        "uptime_seconds": max(0.0, time.time() - STARTED_AT),
        "active_reservations": [public_reservation(item) for item in RESERVATIONS.values()],
        "known_runs": sorted(RUNS),
    }


@app.get("/api/v1/capabilities")
def capabilities() -> dict:
    return {
        "upload_sink": True,
        "iperf3_external": True,
        "irtt_external": True,
        "reservations": True,
    }


@app.post("/api/v1/reservations")
def create_reservation(payload: ReservationCreate) -> dict:
    prune_expired_reservations()
    if RESERVATIONS:
        raise HTTPException(status_code=409, detail="test node already reserved")
    reservation_id = f"res-{uuid4().hex[:12]}"
    RESERVATIONS[reservation_id] = {
        "id": reservation_id,
        "owner": payload.owner,
        "run_id": payload.run_id,
        "created_at": now_iso(),
        "created_epoch": time.time(),
        "ttl_seconds": payload.ttl_seconds,
        "token": f"tok-{uuid4().hex}",
    }
    return RESERVATIONS[reservation_id]


@app.get("/api/v1/reservations/{reservation_id}")
def get_reservation(reservation_id: str) -> dict:
    prune_expired_reservations()
    if reservation_id not in RESERVATIONS:
        raise HTTPException(status_code=404, detail="reservation not found")
    return public_reservation(RESERVATIONS[reservation_id])


@app.patch("/api/v1/reservations/{reservation_id}/renew")
def renew_reservation(reservation_id: str, payload: ReservationRenew) -> dict:
    prune_expired_reservations()
    if reservation_id not in RESERVATIONS:
        raise HTTPException(status_code=404, detail="reservation not found")
    reservation = RESERVATIONS[reservation_id]
    reservation["created_at"] = now_iso()
    reservation["created_epoch"] = time.time()
    if payload.ttl_seconds is not None:
        reservation["ttl_seconds"] = payload.ttl_seconds
    return public_reservation(reservation)


@app.delete("/api/v1/reservations/{reservation_id}")
def delete_reservation(reservation_id: str) -> dict:
    RESERVATIONS.pop(reservation_id, None)
    return {"ok": True}


@app.get("/api/v1/metrics")
def metrics() -> dict:
    return collect_metrics()


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return {"run_id": run_id, "connections": RUNS.get(run_id, [])}


@app.put("/upload/{run_id}")
async def upload_sink(
    run_id: str,
    request: Request,
    x_ltap_token: str | None = Header(default=None),
) -> dict:
    require_reservation(run_id, x_ltap_token)
    started = datetime.now(UTC)
    byte_count = 0
    async for chunk in request.stream():
        byte_count += len(chunk)
    ended = datetime.now(UTC)
    duration = max((ended - started).total_seconds(), 0.000001)
    record = {
        "request_id": f"upload-{uuid4().hex[:12]}",
        "run_id": run_id,
        "source": request.client.host if request.client else None,
        "destination_port": request.url.port,
        "bytes_received": byte_count,
        "started_at": started.replace(microsecond=0).isoformat(),
        "ended_at": ended.replace(microsecond=0).isoformat(),
        "duration_seconds": duration,
        "average_mbit_s": byte_count * 8 / duration / 1_000_000,
        "token_present": bool(x_ltap_token),
    }
    RUNS.setdefault(run_id, []).append(record)
    return record


@app.get("/api/v1/runs/{run_id}/connections")
def run_connections(run_id: str) -> list[dict]:
    return RUNS.get(run_id, [])


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8788)


if __name__ == "__main__":
    main()
