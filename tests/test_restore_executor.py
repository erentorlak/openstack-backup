import pytest

from osbak.models import RestoreOp
from osbak.restore.executor import RebuildExecutor
from osbak.restore.model import RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest


def build_plan():
    return RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()


def test_execute_creates_all_resources_and_records_op(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    mapping = exc.execute(build_plan())

    assert gw.created["servers"][0]["volumes"] == [mapping["volumes"]["v-root"],
                                                   mapping["volumes"]["v-data"]]
    assert gw.created["servers"][0]["ports"] == [mapping["ports"]["port-1"]]
    assert gw.created["servers"][0]["sgs"] == [mapping["security_groups"]["web"]]

    op = session.query(RestoreOp).one()
    assert op.strategy == "rebuild"
    assert op.state == "DONE"
    assert op.restore_point_id == 1
    assert op.error is None
    assert op.finished_at is not None
    assert op.mapping["server"] == mapping["server"]


def test_execute_sg_rules_reference_created_shell(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    exc.execute(build_plan())
    rule_entry = gw.created["sg_rules"][0]
    sg_id = rule_entry["id"]
    assert sg_id == gw.created["security_groups"][0]["id"]
    assert rule_entry["rules"][0]["protocol"] == "tcp"


def test_execute_failure_marks_failed_and_raises(session) -> None:
    class ExplodingGateway(FakeRestoreGateway):
        def create_volume(self, *a, **k):
            raise RuntimeError("boom")

    gw = ExplodingGateway()
    exc = RebuildExecutor(gw, session)
    try:
        exc.execute(build_plan())
        assert False
    except RestorePlanError as exc2:
        assert "boom" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "boom" in op.error
    assert op.finished_at is not None
