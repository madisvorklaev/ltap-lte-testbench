from datetime import UTC, datetime
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="LtAP Test Node")
RUNS: dict[str, list[dict]] = {}
RESERVATIONS: dict[str, dict] = {}


class ReservationCreate(BaseModel):
    owner: str
    run_id: str | None = None
    ttl_seconds: int = 3600


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "utc": now_iso(), "service": "ltap-testnode"}


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
    if RESERVATIONS:
        raise HTTPException(status_code=409, detail="test node already reserved")
    reservation_id = f"res-{uuid4().hex[:12]}"
    RESERVATIONS[reservation_id] = {
        "id": reservation_id,
        "owner": payload.owner,
        "run_id": payload.run_id,
        "created_at": now_iso(),
        "ttl_seconds": payload.ttl_seconds,
    }
    return RESERVATIONS[reservation_id]


@app.get("/api/v1/reservations/{reservation_id}")
def get_reservation(reservation_id: str) -> dict:
    if reservation_id not in RESERVATIONS:
        raise HTTPException(status_code=404, detail="reservation not found")
    return RESERVATIONS[reservation_id]


@app.delete("/api/v1/reservations/{reservation_id}")
def delete_reservation(reservation_id: str) -> dict:
    RESERVATIONS.pop(reservation_id, None)
    return {"ok": True}


@app.put("/upload/{run_id}")
async def upload_sink(
    run_id: str,
    request: Request,
    x_ltap_token: str | None = Header(default=None),
) -> dict:
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
