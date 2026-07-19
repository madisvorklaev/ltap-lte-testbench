import pytest
from pydantic import ValidationError

from ltap_testbench.profiles.schemas import (
    PortRange,
    RouterKindValue,
    RouterPathConfig,
    RouterProfileConfig,
    TestPlanConfig,
    validate_non_overlapping_ports,
)


def test_port_range_requires_order() -> None:
    with pytest.raises(ValidationError):
        PortRange(start=5022, end=5002)


def test_router_path_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        RouterProfileConfig(
            slug="bad-router",
            display_name="Bad Router",
            kind=RouterKindValue.FAKE,
            paths=[RouterPathConfig(id="lte1"), RouterPathConfig(id="lte1")],
        )


def test_mikrotik_profile_requires_management_host() -> None:
    with pytest.raises(ValidationError):
        RouterProfileConfig(
            slug="r1",
            display_name="R1",
            kind=RouterKindValue.MIKROTIK,
            paths=[RouterPathConfig(id="lte1")],
        )


def test_overlapping_ports_are_rejected() -> None:
    paths = [
        RouterPathConfig(id="lte1", ports=PortRange(start=5001, end=5020)),
        RouterPathConfig(id="lte2", ports=PortRange(start=5010, end=5040)),
    ]
    with pytest.raises(ValueError):
        validate_non_overlapping_ports(paths)


def test_test_plan_requires_unique_stages() -> None:
    with pytest.raises(ValidationError):
        TestPlanConfig(
            slug="bad-plan",
            name="Bad Plan",
            stages=["preflight", "preflight"],
        )
