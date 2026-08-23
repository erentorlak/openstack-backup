from __future__ import annotations

import openstack

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, register_check
from osbak.preflight.model import (
    CheckKind,
    CheckResult,
    CheckStatus,
    PlanKind,
)


@register_check
class KeystoneAccess(Check):
    kind = CheckKind.ACCESS
    name = "keystone_access"
    applies_to = frozenset(PlanKind)

    def run(self, ctx: PreflightContext) -> CheckResult:
        try:
            projects = ctx.gateway.list_projects()
        except openstack.exceptions.SDKException as exc:
            return CheckResult(self.name, self.kind, CheckStatus.FAIL, str(exc))
        return CheckResult(
            self.name,
            self.kind,
            CheckStatus.PASS,
            f"{len(projects)} proje",
            {"projects": len(projects)},
        )
