import json
from pathlib import Path

from ltap_testbench.profiles.defaults import QUICK_CHECK_PLAN
from ltap_testbench.profiles.schemas import Stage, TestPlanConfig


def test_quick_check_plan_uses_tcp_stage() -> None:
    assert Stage.TCP_UPLOAD in QUICK_CHECK_PLAN.stages


def test_deploy_plans_validate_and_use_known_stages() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / "deploy").glob("*plan*.json")):
        plan = TestPlanConfig.model_validate(json.loads(path.read_text()))
        assert all(isinstance(stage, Stage) for stage in plan.stages)
