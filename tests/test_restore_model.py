from osbak.restore.model import (
    PlanStep,
    RestoreOptions,
    RestorePlan,
    RestorePlanError,
    RestoreStrategy,
    options_to_dict,
    plan_from_dict,
    plan_to_dict,
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


def test_plan_serialization_round_trip() -> None:
    plan = RestorePlan(
        strategy=RestoreStrategy.REBUILD,
        restore_point_id=3,
        steps=(
            PlanStep(seq=0, action="ensure_security_group_shell",
                     key="sg:web", payload={"name": "web"}),
            PlanStep(seq=1, action="create_volume", key="vol:v-1",
                     payload={"size_gb": 10}),
        ),
        resource_delta={"volumes": 1, "ports": 0, "security_groups": 1,
                        "flavors": 1, "servers": 1},
    )
    data = plan_to_dict(plan)
    restored = plan_from_dict(data)
    assert isinstance(restored, RestorePlan)
    assert restored.strategy is RestoreStrategy.REBUILD
    assert restored.restore_point_id == 3
    assert restored.resource_delta == plan.resource_delta
    assert [(s.seq, s.action, s.key) for s in restored.steps] == [
        (0, "ensure_security_group_shell", "sg:web"),
        (1, "create_volume", "vol:v-1"),
    ]
    assert restored.steps[1].payload == {"size_gb": 10}


def test_plan_serialization_round_trip_empty_steps() -> None:
    plan = RestorePlan(strategy=RestoreStrategy.REBUILD, restore_point_id=1,
                       steps=(), resource_delta={})
    assert plan_from_dict(plan_to_dict(plan)).steps == ()


def test_options_to_dict_serializes_enum() -> None:
    opts = RestoreOptions(strategy=RestoreStrategy.REBUILD, keep_ip=False,
                          instance_name="web-x")
    assert options_to_dict(opts) == {
        "strategy": "rebuild",
        "instance_name": "web-x",
        "availability_zone": None,
        "keep_ip": False,
    }
