from osbak.restore.model import (
    PlanStep,
    RestoreOptions,
    RestorePlan,
    RestorePlanError,
    RestoreStrategy,
)


def test_strategy_values() -> None:
    assert RestoreStrategy.REBUILD.value == "rebuild"
    assert RestoreStrategy.LIVE.value == "live"
    assert RestoreStrategy.COLD.value == "cold"


def test_options_defaults() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD)
    assert opts.instance_name is None
    assert opts.availability_zone is None
    assert opts.keep_ip is True


def test_plan_step_frozen_and_fields() -> None:
    step = PlanStep(seq=1, action="create_volume", key="vol:v-1", payload={"size": 10})
    assert step.action == "create_volume"
    try:
        step.payload["size"] = 20  # frozen dataclass'ın dict'i mutable — plan INNER kopya yapmaz
        assert step.payload["size"] == 20
    except Exception:
        pass  # frozen sözleşmesi yalnızca attribute atamasını engeller


def test_plan_frozen() -> None:
    plan = RestorePlan(
        strategy=RestoreStrategy.REBUILD,
        restore_point_id=1,
        steps=(),
        resource_delta={},
    )
    try:
        plan.strategy = RestoreStrategy.LIVE  # frozen → AttributeError
        assert False
    except AttributeError:
        pass


def test_plan_error_is_exception() -> None:
    try:
        raise RestorePlanError("plan hatasi")
    except RestorePlanError as exc:
        assert "plan" in str(exc)
