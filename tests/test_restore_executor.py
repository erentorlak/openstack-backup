import pytest

from osbak.models import RestoreOp
from osbak.restore.executor import RebuildExecutor
from osbak.restore.model import PlanStep, RestoreOptions, RestorePlan, RestorePlanError, RestoreStrategy
from osbak.restore.planner import RestorePlanner
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest, make_manifest_with_group_ref


def build_plan():
    return RestorePlanner(make_manifest(), RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()


def _planned_op(session, plan):
    op = RestoreOp(restore_point_id=plan.restore_point_id, strategy=plan.strategy.value,
                   state="PLANNED", mapping={})
    session.add(op)
    session.commit()
    return op


def test_execute_creates_all_resources_and_records_op(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    op = _planned_op(session, plan)
    mapping = exc.execute(op, plan)

    assert gw.created["servers"][0]["volumes"] == [mapping["volumes"]["v-root"],
                                                   mapping["volumes"]["v-data"]]
    assert gw.created["servers"][0]["ports"] == [mapping["ports"]["port-1"]]
    assert gw.created["servers"][0]["sgs"] == [mapping["security_groups"]["web"]]

    assert op.strategy == "rebuild"
    assert op.state == "DONE"
    assert op.error is None
    assert op.finished_at is not None

    session.expire_all()
    op2 = session.query(RestoreOp).one()
    assert op2.mapping["server"] == mapping["server"]
    assert set(op2.mapping["volumes"]) == {"v-root", "v-data"}
    assert set(op2.mapping["ports"]) == {"port-1"}
    assert set(op2.mapping["security_groups"]) == {"web"}


def test_execute_sg_rules_reference_created_shell(session) -> None:
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    exc.execute(_planned_op(session, plan), plan)
    rule_entry = gw.created["sg_rules"][0]
    assert rule_entry["id"] == gw.created["security_groups"][0]["id"]
    assert rule_entry["rules"][0]["protocol"] == "tcp"


def test_execute_sg_rules_remote_group_id_resolved_to_new_id(session) -> None:
    plan = RestorePlanner(make_manifest_with_group_ref(),
                          RestoreOptions(strategy=RestoreStrategy.REBUILD), 1).build()
    gw = FakeRestoreGateway()
    exc = RebuildExecutor(gw, session)
    mapping = exc.execute(_planned_op(session, plan), plan)
    rule_by_sg = {e["id"]: e["rules"] for e in gw.created["sg_rules"]}
    db_rule = rule_by_sg[mapping["security_groups"]["db"]][0]
    assert db_rule["remote_group_id"] == mapping["security_groups"]["web"]
    assert "remote_group_name" not in db_rule


def test_execute_unknown_action_marks_failed(session) -> None:
    plan = RestorePlan(strategy=RestoreStrategy.REBUILD, restore_point_id=1,
                       steps=(PlanStep(seq=0, action="warp", key="x", payload={}),),
                       resource_delta={})
    exc = RebuildExecutor(FakeRestoreGateway(), session)
    try:
        exc.execute(_planned_op(session, plan), plan)
        assert False
    except RestorePlanError as exc2:
        assert "bilinmeyen adim" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "bilinmeyen adim" in op.error
    assert op.finished_at is not None


def test_execute_failure_marks_failed_and_raises(session) -> None:
    class ExplodingGateway(FakeRestoreGateway):
        def create_volume(self, *a, **k):
            raise RuntimeError("boom")

    gw = ExplodingGateway()
    exc = RebuildExecutor(gw, session)
    plan = build_plan()
    try:
        exc.execute(_planned_op(session, plan), plan)
        assert False
    except RestorePlanError as exc2:
        assert "boom" in str(exc2)

    op = session.query(RestoreOp).one()
    assert op.state == "FAILED"
    assert "boom" in op.error
    assert op.finished_at is not None

    session.expire_all()
    op = session.query(RestoreOp).one()
    assert set(op.mapping["security_groups"]) == {"web"}
    assert op.mapping["volumes"] == {}
