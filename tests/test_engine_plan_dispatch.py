from types import SimpleNamespace
from typing import Any, cast

from ltap_testbench.jobs.engine import (
    _plan_has_udp_upload_stage,
    _plan_has_upload_stage,
    _plan_has_video_probe_stage,
)


def test_udp_upload_stage_does_not_match_tcp_upload() -> None:
    run = cast(Any, SimpleNamespace(resolved_plan={"stages": ["udp-upload"]}))

    assert _plan_has_upload_stage(run) is False
    assert _plan_has_udp_upload_stage(run) is True


def test_video_probe_requires_exact_stage() -> None:
    run = cast(Any, SimpleNamespace(resolved_plan={"stages": ["udp-upload"], "video_probe": {}}))

    assert _plan_has_video_probe_stage(run) is False

    run.resolved_plan["stages"].append("video-udp-probe")
    assert _plan_has_video_probe_stage(run) is True
