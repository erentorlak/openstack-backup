import openstack
import pytest

from osbak.preflight.context import PreflightContext
from osbak.preflight.engine import ValidationEngine
from osbak.preflight.model import CheckStatus, PlanKind
from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.preflight.rules import instances, keystone  # noqa: F401  (register checks)
from tests.fake_gateway import FakeGateway


class _SdkErrorGateway:
    def list_projects(self):
        raise openstack.exceptions.SDKException("auth failed")

    def list_servers(self, project_id: str):
        return []


class _BoomGateway:
    def list_projects(self):
        raise RuntimeError("boom")


def test_keystone_erisim_pass() -> None:
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")]),
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["keystone_erisim"])
    assert report.results[0].status is CheckStatus.PASS
    assert report.results[0].data["projects"] == 1


def test_keystone_erisim_fail_on_sdk_error() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=_SdkErrorGateway())
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["keystone_erisim"])
    assert report.results[0].status is CheckStatus.FAIL


def test_non_sdk_exception_propagates() -> None:
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=_BoomGateway())
    with pytest.raises(RuntimeError):
        ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["keystone_erisim"])


def test_instance_mevcut_pass_and_data() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="i-1"
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.PASS
    assert report.results[0].data["server_id"] == "i-1"


def test_instance_mevcut_populates_ctx() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="i-1")
    ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert ctx.data["project_id"] == "pid-1"


def test_instance_mevcut_fail_when_missing() -> None:
    gateway = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")], servers={"pid-1": []})
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT, gateway=gateway, instance_uuid="nope"
    )
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.FAIL


def test_instance_mevcut_fail_when_none() -> None:
    gateway = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")])
    ctx = PreflightContext(plan_kind=PlanKind.SNAPSHOT, gateway=gateway)
    report = ValidationEngine().validate(PlanKind.SNAPSHOT, ctx, only=["instance_mevcut"])
    assert report.results[0].status is CheckStatus.FAIL


def test_instance_durum_pass_and_fail() -> None:
    server = ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
    gateway = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
    )
    ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=gateway,
        instance_uuid="i-1",
        goal_state="ACTIVE",
    )
    report = ValidationEngine().validate(
        PlanKind.SNAPSHOT, ctx, only=["instance_mevcut", "instance_durum"]
    )
    assert report.passed is True
    fail_ctx = PreflightContext(
        plan_kind=PlanKind.SNAPSHOT,
        gateway=gateway,
        instance_uuid="i-1",
        goal_state="STOPPED",
    )
    fail_report = ValidationEngine().validate(
        PlanKind.SNAPSHOT, fail_ctx, only=["instance_mevcut", "instance_durum"]
    )
    assert any(r.status is CheckStatus.FAIL for r in fail_report.results)
