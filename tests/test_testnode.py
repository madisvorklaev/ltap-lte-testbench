from fastapi.testclient import TestClient
from ltap_testnode.app import RESERVATIONS, RUNS, app


def test_testnode_status_and_metrics() -> None:
    RUNS.clear()
    RESERVATIONS.clear()
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["version"]
    assert health.json()["measurement_implementation_version"]
    assert health.json()["capability_schema_version"]

    status = client.get("/api/v1/status")
    assert status.status_code == 200
    assert status.json()["ok"] is True

    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert "network" in metrics.json()


def test_testnode_reservation_conflict_and_release() -> None:
    RUNS.clear()
    RESERVATIONS.clear()
    client = TestClient(app)

    first = client.post("/api/v1/reservations", json={"owner": "pytest", "run_id": "run-a"})
    assert first.status_code == 200
    second = client.post("/api/v1/reservations", json={"owner": "pytest", "run_id": "run-b"})
    assert second.status_code == 409

    reservation_id = first.json()["id"]
    assert first.json()["token"].startswith("tok-")
    assert "token" not in client.get("/api/v1/status").json()["active_reservations"][0]
    renewed = client.patch(
        f"/api/v1/reservations/{reservation_id}/renew",
        json={"ttl_seconds": 120},
    )
    assert renewed.status_code == 200
    assert renewed.json()["ttl_seconds"] == 120
    deleted = client.delete(f"/api/v1/reservations/{reservation_id}")
    assert deleted.status_code == 200
    third = client.post("/api/v1/reservations", json={"owner": "pytest", "run_id": "run-c"})
    assert third.status_code == 200


def test_testnode_upload_sink_records_connection() -> None:
    RUNS.clear()
    RESERVATIONS.clear()
    client = TestClient(app)

    reservation = client.post(
        "/api/v1/reservations",
        json={"owner": "pytest", "run_id": "run-upload"},
    )
    token = reservation.json()["token"]

    response = client.put("/upload/run-upload", content=b"abc", headers={"X-Ltap-Token": token})
    assert response.status_code == 200
    assert response.json()["bytes_received"] == 3

    run = client.get("/api/v1/runs/run-upload")
    assert run.status_code == 200
    assert run.json()["connections"][0]["bytes_received"] == 3


def test_testnode_upload_sink_rejects_missing_or_mismatched_reservation() -> None:
    RUNS.clear()
    RESERVATIONS.clear()
    client = TestClient(app)
    reservation = client.post(
        "/api/v1/reservations",
        json={"owner": "pytest", "run_id": "run-a"},
    )

    missing = client.put("/upload/run-a", content=b"abc")
    wrong_run = client.put(
        "/upload/run-b",
        content=b"abc",
        headers={"X-Ltap-Token": reservation.json()["token"]},
    )

    assert missing.status_code == 401
    assert wrong_run.status_code == 403
