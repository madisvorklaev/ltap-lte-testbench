from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.db.models import RouterKind, RouterProfile, TestPlan

QUICK_CHECK_PLAN = {
    "stages": ["preflight", "path-verification", "idle-latency", "short-upload"],
    "latency": {"duration_seconds": 60, "interval_ms": 100},
    "tcp_upload": {"duration_seconds": 30, "parallel_streams": [1]},
    "telemetry": {"controller_interval_seconds": 1, "lte_interval_seconds": 5},
    "temporary_router_changes": {"disable_fasttrack": False},
}


def seed_demo_data(session: Session) -> None:
    if session.scalar(select(RouterProfile).where(RouterProfile.slug == "demo-generic")) is None:
        session.add(
            RouterProfile(
                slug="demo-generic",
                display_name="Demo Generic Router",
                kind=RouterKind.GENERIC,
                expected_gateway=None,
                controller_interface=None,
                metadata_json={"paths": [{"id": "wan", "label": "Generic WAN"}]},
            )
        )
    if session.scalar(select(RouterProfile).where(RouterProfile.slug == "demo-fake-ltap")) is None:
        session.add(
            RouterProfile(
                slug="demo-fake-ltap",
                display_name="Demo Fake Dual-LTE LtAP",
                kind=RouterKind.FAKE,
                metadata_json={
                    "paths": [
                        {"id": "lte1", "port": 5002, "routing_table": "to-lte1"},
                        {"id": "lte2", "port": 5022, "routing_table": "to-lte2"},
                    ]
                },
            )
        )
    if session.scalar(select(TestPlan).where(TestPlan.slug == "quick-check")) is None:
        session.add(
            TestPlan(
                slug="quick-check",
                name="Quick Health Check",
                definition=QUICK_CHECK_PLAN,
            )
        )
    session.commit()
