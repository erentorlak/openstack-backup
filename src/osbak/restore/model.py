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
