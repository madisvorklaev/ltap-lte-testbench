from typing import ClassVar

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import RunEvent
from ltap_testbench.jobs.engine import create_run, execute_run
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.profiles.schemas import ServerProfileConfig, TestPlanConfig
from ltap_testbench.profiles.service import create_server_profile, create_test_plan
from ltap_testbench.testnode.client import TestNodeReservation


class RecordingTestNodeClient:
    created: ClassVar[list[tuple[str, str | None, int]]] = []
    released: ClassVar[list[str]] = []

    def __init__(self, base_url: str):
        self.base_url = base_url

    def create_reservation(
        self,
        owner: str,
        run_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> TestNodeReservation:
        self.created.append((owner, run_id, ttl_seconds))
        return TestNodeReservation(
            id="res-test",
            owner=owner,
            run_id=run_id,
            ttl_seconds=ttl_seconds,
        )

    def release_reservation(self, reservation_id: str) -> None:
        self.released.append(reservation_id)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_execute_run_reserves_and_releases_configured_test_node(session_factory) -> None:
    RecordingTestNodeClient.created = []
    RecordingTestNodeClient.released = []
    with session_factory() as session:
        seed_demo_data(session)
        create_server_profile(
            session,
            ServerProfileConfig(
                slug="stockbot",
                display_name="Stockbot",
                control_api_url="http://192.168.71.8:8088",
            ),
        )
        create_test_plan(
            session,
            TestPlanConfig(
                slug="with-server",
                name="With Server",
                server_slug="stockbot",
                stages=["preflight", "path-verification"],
            ),
        )

        run = create_run(session, "demo-generic", "with-server")
        execute_run(session, run, client_factory=RecordingTestNodeClient)

        assert RecordingTestNodeClient.created == [("ltap-testbench", run.run_id, 3600)]
        assert RecordingTestNodeClient.released == ["res-test"]
        assert run.summary["test_node_reserved"] is True

        events = session.scalars(select(RunEvent).order_by(RunEvent.id)).all()
        event_types = [event.event_type for event in events]
        assert "server-reservation" in event_types
        assert "server-release" in event_types
