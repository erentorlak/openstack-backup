from __future__ import annotations

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
)


@register_check
class OrjinalInstanceYok(Check):
    kind = CheckKind.CAKISMA
    name = "orjinal_instance_yok"
    applies_to = frozenset({PlanKind.RESTORE})

    def run(self, ctx: PreflightContext) -> CheckResult:
        uuid = ctx.instance_uuid
        if uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        for project in ctx.gateway.list_projects():
            for server in ctx.gateway.list_servers(project.id):
                if server.id == uuid:
                    return CheckResult(
                        self.name, self.kind, CheckStatus.FAIL,
                        f"orijinal instance hala mevcut: {uuid} — once sil/durdur",
                    )
        return CheckResult(self.name, self.kind, CheckStatus.PASS,
                           "orijinal instance yok — rebuild uygun")
