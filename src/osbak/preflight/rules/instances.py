from __future__ import annotations

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind


@register_check
class InstanceMevcut(Check):
    kind = CheckKind.DURUM
    name = "instance_mevcut"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP, PlanKind.ROLLBACK})

    def run(self, ctx: PreflightContext) -> CheckResult:
        uuid = ctx.instance_uuid
        if uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        for project in ctx.gateway.list_projects():
            for server in ctx.gateway.list_servers(project.id):
                if server.id == uuid:
                    ctx.data["server"] = server
                    ctx.data["project_id"] = project.id
                    return CheckResult(
                        self.name,
                        self.kind,
                        CheckStatus.PASS,
                        f"bulundu: {project.id}/{server.id}",
                        {"project_id": project.id, "server_id": server.id},
                    )
        return CheckResult(self.name, self.kind, CheckStatus.FAIL, f"instance yok: {uuid}")


@register_check
class InstanceDurum(Check):
    kind = CheckKind.DURUM
    name = "instance_durum"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP})

    def run(self, ctx: PreflightContext) -> CheckResult:
        if ctx.goal_state is None:
            return CheckResult(self.name, self.kind, CheckStatus.PASS, "durum hedefi yok")
        server = ctx.data.get("server")
        if server is None or server.status != ctx.goal_state:
            return CheckResult(
                self.name,
                self.kind,
                CheckStatus.FAIL,
                f"beklenen: {ctx.goal_state}, gerçek: {server.status if server else 'yok'}",
            )
        return CheckResult(self.name, self.kind, CheckStatus.PASS, f"durum: {server.status}")
