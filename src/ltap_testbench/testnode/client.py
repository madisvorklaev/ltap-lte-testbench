from dataclasses import dataclass
from typing import ClassVar

import httpx


@dataclass(frozen=True)
class TestNodeReservation:
    __test__: ClassVar[bool] = False

    id: str
    owner: str
    run_id: str | None
    ttl_seconds: int


class TestNodeClient:
    __test__: ClassVar[bool] = False

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def _client(self) -> httpx.Client:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self.transport,
        )

    def health(self) -> dict:
        with self._client() as client:
            response = client.get("/api/v1/health")
            response.raise_for_status()
            return response.json()

    def status(self) -> dict:
        with self._client() as client:
            response = client.get("/api/v1/status")
            response.raise_for_status()
            return response.json()

    def metrics(self) -> dict:
        with self._client() as client:
            response = client.get("/api/v1/metrics")
            response.raise_for_status()
            return response.json()

    def run_connections(self, run_id: str) -> list[dict]:
        with self._client() as client:
            response = client.get(f"/api/v1/runs/{run_id}/connections")
            response.raise_for_status()
            return response.json()

    def video_frame_stats(
        self,
        run_id: str,
        finalize: bool = False,
        delete: bool = False,
    ) -> dict:
        with self._client() as client:
            response = client.get(
                f"/api/v1/runs/{run_id}/video-frames",
                params={"finalize": finalize, "delete": delete},
            )
            response.raise_for_status()
            return response.json()

    def create_reservation(
        self,
        owner: str,
        run_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> TestNodeReservation:
        with self._client() as client:
            response = client.post(
                "/api/v1/reservations",
                json={"owner": owner, "run_id": run_id, "ttl_seconds": ttl_seconds},
            )
            response.raise_for_status()
            data = response.json()
            return TestNodeReservation(
                id=data["id"],
                owner=data["owner"],
                run_id=data.get("run_id"),
                ttl_seconds=data["ttl_seconds"],
            )

    def release_reservation(self, reservation_id: str) -> None:
        with self._client() as client:
            response = client.delete(f"/api/v1/reservations/{reservation_id}")
            response.raise_for_status()
