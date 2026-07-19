from sqlalchemy import select
from sqlalchemy.orm import Session

from ltap_testbench.db.models import RouterKind, RouterProfile, TestPlan
from ltap_testbench.profiles.schemas import RouterProfileConfig, TestPlanConfig


def create_router_profile(session: Session, config: RouterProfileConfig) -> RouterProfile:
    existing = session.scalar(select(RouterProfile).where(RouterProfile.slug == config.slug))
    if existing is not None:
        raise ValueError(f"router profile already exists: {config.slug}")
    router = RouterProfile(
        slug=config.slug,
        display_name=config.display_name,
        kind=RouterKind(config.kind.value),
        management_host=config.management_host,
        management_protocol=config.management_protocol,
        username=config.username,
        secret_ref=config.secret_ref,
        expected_gateway=config.expected_gateway,
        controller_interface=config.controller_interface,
        allow_configuration_changes=config.allow_configuration_changes,
        metadata_json={
            "paths": [path.model_dump(mode="json") for path in config.paths],
            **config.metadata,
        },
    )
    session.add(router)
    session.commit()
    return router


def create_test_plan(session: Session, config: TestPlanConfig) -> TestPlan:
    existing = session.scalar(select(TestPlan).where(TestPlan.slug == config.slug))
    if existing is not None:
        raise ValueError(f"test plan already exists: {config.slug}")
    plan = TestPlan(
        slug=config.slug,
        name=config.name,
        version=config.version,
        definition=config.model_dump(mode="json"),
    )
    session.add(plan)
    session.commit()
    return plan
