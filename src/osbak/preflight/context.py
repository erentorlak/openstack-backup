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

    def find_server(self, instance_uuid: str | None = None) -> tuple[str, Any] | None:
        """Locate an instance across all projects; return (project_id, server) or None.

        Single home for the project/server scan shared by InstancePresent and
        OriginalInstanceAbsent instead of duplicated loops.
        """
        uuid = instance_uuid if instance_uuid is not None else self.instance_uuid
        if uuid is None:
            return None
        for project in self.gateway.list_projects():
            for server in self.gateway.list_servers(project.id):
                if server.id == uuid:
                    return project.id, server
        return None
