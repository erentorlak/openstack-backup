import pytest

from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import Check, ValidationEngine, checks_for, register_check
from osbak.preflight.model import CheckKind, CheckResult, CheckStatus, PlanKind
from tests.fake_gateway import FakeGateway


@register_check
class AlwaysPass(Check):
    kind = CheckKind.STATE
    name = "always_pass"
    applies_to = frozenset({PlanKind.SNAPSHOT, PlanKind.BACKUP})

    def run(self, ctx: PreflightContext) -> CheckResult:
        return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")


@register_check
class SnapshotOnlyCheck(Check):
    kind = CheckKind.ACCESS
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


def test_validate_only_with_unknown_name_raises() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=FakeGateway(projects=[]))
    with pytest.raises(ValueError):
        ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["no_such_check"])


def test_find_server_locates_and_returns_project() -> None:
    server = ServerInfo(id="i-1", name="w", project_id="p-1", status="ACTIVE", flavor_id="f-1")
    gw = FakeGateway(
        projects=[ProjectInfo(id="p-1", name="a")],
        servers={"p-1": [server]},
        volumes={"p-1": []},
    )
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gw, instance_uuid="i-1")
    found = ctx.find_server()
    assert found is not None
    project_id, found_server = found
    assert project_id == "p-1"
    assert found_server.id == "i-1"


def test_find_server_returns_none_when_absent() -> None:
    gw = FakeGateway(
        projects=[ProjectInfo(id="p-1", name="a")],
        servers={"p-1": [ServerInfo(id="i-2", name="w", project_id="p-1", status="ACTIVE", flavor_id="f-1")]},
        volumes={"p-1": []},
    )
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gw, instance_uuid="missing")
    assert ctx.find_server() is None


def test_duplicate_registration_raises() -> None:
    with pytest.raises(ValueError):

        @register_check
        class Duplicate(AlwaysPass):
            name = "always_pass"


def test_duplicate_registration_is_atomic() -> None:
    with pytest.raises(ValueError):

        @register_check
        class PartialProbe(Check):
            kind = CheckKind.ACCESS
            name = "snapshot_only"
            applies_to = frozenset({PlanKind.RESTORE, PlanKind.SNAPSHOT})

            def run(self, ctx: PreflightContext) -> CheckResult:
                return CheckResult(self.name, self.kind, CheckStatus.PASS, "ok")

    assert not any(c.name == "snapshot_only" for c in checks_for(PlanKind.RESTORE))
