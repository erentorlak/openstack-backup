from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class RestoreStrategy(str, enum.Enum):
    REBUILD = "rebuild"
    LIVE = "live"
    COLD = "cold"


class RestorePlanError(Exception):
    pass


@dataclass(frozen=True)
class RestoreOptions:
    strategy: RestoreStrategy
    instance_name: str | None = None
    availability_zone: str | None = None
    keep_ip: bool = True


@dataclass(frozen=True)
class PlanStep:
    seq: int
    action: str
    key: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RestorePlan:
    strategy: RestoreStrategy
    restore_point_id: int
    steps: tuple[PlanStep, ...]
    resource_delta: dict[str, int]


def plan_to_dict(plan: RestorePlan) -> dict:
    return {
        "strategy": plan.strategy.value,
        "restore_point_id": plan.restore_point_id,
        "resource_delta": dict(plan.resource_delta),
        "steps": [
            {"seq": s.seq, "action": s.action, "key": s.key,
             "payload": dict(s.payload)}
            for s in plan.steps
        ],
    }


def plan_from_dict(data: dict) -> RestorePlan:
    return RestorePlan(
        strategy=RestoreStrategy(data["strategy"]),
        restore_point_id=data["restore_point_id"],
        steps=tuple(
            PlanStep(seq=s["seq"], action=s["action"], key=s["key"],
                     payload=dict(s["payload"]))
            for s in data["steps"]
        ),
        resource_delta=dict(data["resource_delta"]),
    )


def options_to_dict(options: RestoreOptions) -> dict:
    return {
        "strategy": options.strategy.value,
        "instance_name": options.instance_name,
        "availability_zone": options.availability_zone,
        "keep_ip": options.keep_ip,
    }
