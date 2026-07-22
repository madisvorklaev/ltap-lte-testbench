import httpx

from ltap_testbench.testnode.client import TestNodeClient


def test_testnode_client_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(200, json={"ok": True})

    client = TestNodeClient("http://testnode", transport=httpx.MockTransport(handler))
    assert client.health()["ok"] is True


def test_testnode_client_reservation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": "res-1",
                    "owner": "pytest",
                    "run_id": "run-1",
                    "ttl_seconds": 60,
                    "token": "tok-test",
                },
            )
        if request.method == "PATCH":
            assert request.url.path == "/api/v1/reservations/res-1/renew"
            return httpx.Response(200, json={"id": "res-1", "ttl_seconds": 120})
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/reservations/res-1"
        return httpx.Response(200, json={"ok": True})

    client = TestNodeClient("http://testnode", transport=httpx.MockTransport(handler))
    reservation = client.create_reservation("pytest", run_id="run-1", ttl_seconds=60)
    assert reservation.id == "res-1"
    assert reservation.token == "tok-test"
    assert client.renew_reservation(reservation.id, ttl_seconds=120)["ttl_seconds"] == 120
    client.release_reservation(reservation.id)


def test_testnode_client_run_connections() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/runs/run-a/connections"
        return httpx.Response(200, json=[{"bytes_received": 123}])

    client = TestNodeClient("http://testnode", transport=httpx.MockTransport(handler))
    assert client.run_connections("run-a")[0]["bytes_received"] == 123


def test_testnode_client_raises_for_unhealthy_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False})

    client = TestNodeClient("http://testnode", transport=httpx.MockTransport(handler))
    try:
        client.health()
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 503
    else:
        raise AssertionError("expected HTTPStatusError")
