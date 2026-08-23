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
class OriginalInstanceAbsent(Check):
    kind = CheckKind.CONFLICT
    name = "original_instance_absent"
    applies_to = frozenset({PlanKind.RESTORE})

    def run(self, ctx: PreflightContext) -> CheckResult:
        if ctx.instance_uuid is None:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, "instance belirtilmedi")
        if ctx.find_server(ctx.instance_uuid) is not None:
            return CheckResult(
                self.name, self.kind, CheckStatus.FAIL,
                f"orijinal instance hala mevcut: {ctx.instance_uuid} — once sil",
            )
        return CheckResult(self.name, self.kind, CheckStatus.PASS,
                           "orijinal instance yok — rebuild uygun")
