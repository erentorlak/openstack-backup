import pytest

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, ValidationEngine, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind
from tests.fake_gateway import FakeGateway


@register_check
class AlwaysPass(Check):
    kind = CheckKind.DURUM
    name = "always_pass"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP})

    def run(self, ctx: PreflightContext) -> CheckResult:
        return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")


@register_check
class SnapshotOnlyCheck(Check):
    kind = CheckKind.ERISIM
    name = "snapshot_only"
    applies_to = frozenset({PlanKind.SNAPSHOT})

    def run(self, ctx: PreflightContext) -> CheckResult:
        return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")


def test_validate_runs_applicable_checks() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(
        PlanKind.SNAPSHOT, ctx, only=["always_pass", "snapshot_only"]
    )
    assert {r.name for r in report.results} == {"always_pass", "snapshot_only"}
    assert report.passed is True


def test_validate_backup_excludes_snapshot_only() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.BACKUP, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(PlanKind.BACKUP, ctx, only=["always_pass", "snapshot_only"])
    assert {r.name for r in report.results} == {"always_pass"}


def test_validate_only_restricts_to_named_checks() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=FakeGateway(projects=[]))
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["snapshot_only"])
    assert [r.name for r in report.results] == ["snapshot_only"]


def test_duplicate_registration_raises() -> None:
    with pytest.raises(ValueError):

        @register_check
        class Duplicate(AlwaysPass):
            name = "always_pass"
