import pytest
from pydantic import ValidationError

from ltap_testbench.profiles.schemas import (
    PortRange,
    RouterKindValue,
    RouterPathConfig,
    RouterProfileConfig,
    Stage,
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


def test_test_plan_accepts_server_slug() -> None:
    plan = TestPlanConfig(
        slug="server-plan",
        name="Server Plan",
        server_slug="stockbot",
        stages=["tcp-upload"],
    )
    assert plan.server_slug == "stockbot"


def test_test_plan_keeps_video_tcp_count_and_udp_pattern() -> None:
    plan = TestPlanConfig(
        slug="video-plan",
        name="Video Plan",
        server_slug="stockbot",
        stages=["tcp-upload", "udp-upload", "video-udp-probe"],
        tcp_upload={"duration_seconds": 10, "count": 3},
        udp_upload={"duration_seconds": 5, "bitrate_mbit_s": 1, "pattern": "after_each_tcp"},
        video_probe={"duration_seconds": 5, "bitrate_mbit_s": 2, "fps": 25},
    )

    assert plan.tcp_upload.count == 3
    assert plan.udp_upload.pattern == "after_each_tcp"
    assert plan.video_probe.duration_seconds == 5


def test_test_plan_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TestPlanConfig(
            slug="bad-extra",
            name="Bad Extra",
            stages=["tcp-upload"],
            video_probe={"duration_seconds": 5, "unexpected": True},
        )


def test_test_plan_migrates_short_upload_alias() -> None:
    plan = TestPlanConfig(
        slug="alias-plan",
        name="Alias Plan",
        stages=["preflight", "short-upload"],
    )

    assert plan.stages == [Stage.PREFLIGHT, Stage.TCP_UPLOAD]


def test_test_plan_rejects_unknown_stage() -> None:
    with pytest.raises(ValidationError):
        TestPlanConfig(slug="bad-stage", name="Bad Stage", stages=["short-uplaod"])


def test_udp_after_each_tcp_requires_tcp_stage() -> None:
    with pytest.raises(ValidationError):
        TestPlanConfig(
            slug="bad-pattern",
            name="Bad Pattern",
            stages=["udp-upload"],
            udp_upload={"pattern": "after_each_tcp"},
        )
