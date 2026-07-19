from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.db.models import RouterKind, RouterProfile, TestPlan
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
        session.add(
            RouterProfile(
                slug=generic.slug,
                display_name=generic.display_name,
                kind=RouterKind.GENERIC,
                expected_gateway=generic.expected_gateway,
                controller_interface=generic.controller_interface,
                metadata_json={
                    "paths": [path.model_dump(mode="json") for path in generic.paths],
                    **generic.metadata,
                },
            )
        )
    if session.scalar(select(RouterProfile).where(RouterProfile.slug == "demo-fake-ltap")) is None:
        session.add(
            RouterProfile(
                slug=fake_ltap.slug,
                display_name=fake_ltap.display_name,
                kind=RouterKind.FAKE,
                metadata_json={
                    "paths": [path.model_dump(mode="json") for path in fake_ltap.paths],
                    **fake_ltap.metadata,
                },
            )
        )
    if session.scalar(select(TestPlan).where(TestPlan.slug == "quick-check")) is None:
        session.add(
            TestPlan(
                slug=QUICK_CHECK_PLAN.slug,
                name=QUICK_CHECK_PLAN.name,
                version=QUICK_CHECK_PLAN.version,
                definition=QUICK_CHECK_PLAN.model_dump(mode="json"),
            )
        )
    session.commit()
