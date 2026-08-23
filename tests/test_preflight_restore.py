from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import CheckStatus, PlanKind
from osbak.preflight.rules import restore  # noqa: F401  (register)
from tests.fake_gateway import FakeGateway


def _server(pid="p-1"):
    return ServerInfo(id="orig-uuid", name="web", project_id=pid,
                      status="ACTIVE", flavor_id="f1")


def test_orjinal_instance_yok_pass_when_absent() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw,
                           instance_uuid="orig-uuid")
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.PASS
    assert report.passed


def test_orjinal_instance_yok_fail_when_still_present() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")],
                     servers={"p-1": [_server()]})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw,
                           instance_uuid="orig-uuid")
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.FAIL
    assert "hala mevcut" in found.message
    assert not report.passed


def test_orjinal_instance_yok_requires_uuid() -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})
    ctx = PreflightContext(plan_kind=PlanKind.RESTORE, gateway=gw)
    report = ValidationEngine().validate(PlanKind.RESTORE, ctx)
    found = next(r for r in report.results if r.name == "orjinal_instance_yok")
    assert found.status is CheckStatus.FAIL
    assert "belirtilmedi" in found.message
