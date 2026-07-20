from fastapi.testclient import TestClient

from ltap_testbench.api.app import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_router_preflight_api() -> None:
    client = TestClient(app)
    client.post("/api/v1/demo/seed")
    response = client.post("/api/v1/routers/demo-generic/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "controller" in payload
    assert payload["router"][0]["ok"] is True
