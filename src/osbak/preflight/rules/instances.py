from __future__ import annotations

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind


@register_check
class InstancePresent(Check):
    kind = CheckKind.STATE
    name = "instance_present"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP, PlanKind.ROLLBACK})

    def run(self, ctx: PreflightContext) -> CheckResult:
        if ctx.instance_uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        found = ctx.find_server(ctx.instance_uuid)
        if found is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, f"instance yok: {ctx.instance_uuid}")
        project_id, server = found
        ctx.data["server"] = server
        ctx.data["project_id"] = project_id
        return CheckResult(
            self.name,
            self.kind,
            CheckStatus.PASS,
            f"bulundu: {project_id}/{server.id}",
            {"project_id": project_id, "server_id": server.id},
        )


@register_check
class InstanceState(Check):
    kind = CheckKind.STATE
    name = "instance_state"
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
