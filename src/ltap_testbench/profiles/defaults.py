from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.db.models import RouterProfile, TestPlan
from ltap_testbench.profiles.schemas import (
    LatencyStageConfig,
    PortRange,
    RouterKindValue,
    RouterPathConfig,
    RouterProfileConfig,
    TcpUploadStageConfig,
    TemporaryRouterChangesConfig,
    TestPlanConfig,
)
from ltap_testbench.profiles.service import create_router_profile, create_test_plan

QUICK_CHECK_PLAN = TestPlanConfig(
    slug="quick-check",
    name="Quick Health Check",
    stages=["preflight", "path-verification", "idle-latency", "short-upload"],
    latency=LatencyStageConfig(duration_seconds=60, interval_ms=100),
    tcp_upload=TcpUploadStageConfig(duration_seconds=30, parallel_streams=[1]),
    telemetry={"controller_interval_seconds": 1, "lte_interval_seconds": 5},
    temporary_router_changes=TemporaryRouterChangesConfig(disable_fasttrack=False),
)


def seed_demo_data(session: Session) -> None:
    generic = RouterProfileConfig(
        slug="demo-generic",
        display_name="Demo Generic Router",
        kind=RouterKindValue.GENERIC,
        paths=[RouterPathConfig(id="wan", label="Generic WAN")],
    )
    fake_ltap = RouterProfileConfig(
        slug="demo-fake-ltap",
        display_name="Demo Fake Dual-LTE LtAP",
        kind=RouterKindValue.FAKE,
        paths=[
            RouterPathConfig(
                id="lte1",
                ports=PortRange(start=5002, end=5002),
                routing_table="to-lte1",
            ),
            RouterPathConfig(
                id="lte2",
                ports=PortRange(start=5022, end=5022),
                routing_table="to-lte2",
            ),
        ],
    )
    if session.scalar(select(RouterProfile).where(RouterProfile.slug == "demo-generic")) is None:
        create_router_profile(session, generic)
    if session.scalar(select(RouterProfile).where(RouterProfile.slug == "demo-fake-ltap")) is None:
        create_router_profile(session, fake_ltap)
    if session.scalar(select(TestPlan).where(TestPlan.slug == "quick-check")) is None:
        create_test_plan(session, QUICK_CHECK_PLAN)
    session.commit()
