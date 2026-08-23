from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from osbak.discovery.gateway import OpenstackGateway
from osbak.preflight.model import PlanKind


@dataclass
class PreflightContext:
    plan_kind: PlanKind
    gateway: OpenstackGateway
    instance_uuid: str | None = None
    project_id: str | None = None
    goal_state: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
