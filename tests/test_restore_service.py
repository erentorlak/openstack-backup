import pytest

from osbak.discovery.gateway import ProjectInfo, ServerInfo
from osbak.models import Instance, Project, RestoreOp, RestorePoint
from osbak.restore.model import RestoreOptions, RestorePlanError, RestoreStrategy
from osbak.restore.restore_service import RestorePreflightFailed, RestoreService
from tests.fake_gateway import FakeGateway
from tests.fake_restore_gateway import FakeRestoreGateway
from tests.test_restore_planner import make_manifest


def _seed_point(session, manifest, instance_uuid="orig-uuid"):
    # NOT: make_manifest(): instance dict'inde "id" YOK; apply, manifest["instance"]["id"]
    # okur (OrjinalInstanceYok icin) -> test manifestine id enjekte edilir.
    manifest = dict(manifest)
    manifest["instance"] = dict(manifest["instance"])
    manifest["instance"]["id"] = instance_uuid
    proj = Project(keystone_project_id="p-1")
    session.add(proj)
    session.flush()
    inst = Instance(instance_uuid=instance_uuid, project_id=proj.id)
    session.add(inst)
    session.flush()
    point = RestorePoint(kind="snapshot", instance_id=inst.id, manifest=manifest)
    session.add(point)
    session.commit()
    return point


def _empty_gw():
    return FakeGateway(projects=[ProjectInfo(id="p-1", name="a")], servers={})


def _service(session, gw=None, mutators=None):
    return RestoreService(
        session,
        gw or _empty_gw(),
        mutators or (lambda: FakeRestoreGateway()),
    )


def test_plan_creates_planned_op(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = session.get(RestoreOp, op_id)
    assert op is not None
    assert op.state == "PLANNED"
    assert op.strategy == "rebuild"
    assert op.plan["strategy"] == "rebuild"
    assert op.plan["steps"][-1]["action"] == "create_server"
    assert op.options == {"strategy": "rebuild", "instance_name": None,
                          "availability_zone": None, "keep_ip": True}


def test_plan_rejects_live_strategy(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    try:
        svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.LIVE))
        assert False
    except RestorePlanError as exc:
        assert "desteklenmiyor" in str(exc)


def test_plan_rejects_missing_point(session) -> None:
    svc = _service(session)
    try:
        svc.plan(999, RestoreOptions(strategy=RestoreStrategy.REBUILD))
        assert False
    except RestorePlanError as exc:
        assert "restore point yok" in str(exc)


def test_apply_executes_to_done(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    mut = FakeRestoreGateway()
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    result = RestoreService(session, _empty_gw(), lambda: mut).apply(op_id)
    assert result.state == "DONE"
    assert result.server_id is not None
    assert len(mut.created["servers"]) == 1
    op = session.get(RestoreOp, op_id)
    assert op.mapping["server"] == result.server_id


def test_apply_preflight_fails_when_original_running(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    gw = FakeGateway(
        projects=[ProjectInfo(id="p-1", name="a")],
        servers={"p-1": [ServerInfo(id="orig-uuid", name="web", project_id="p-1",
                                    status="ACTIVE", flavor_id="f-1")]},
    )
    svc = RestoreService(session, gw, lambda: FakeRestoreGateway())
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    try:
        svc.apply(op_id)
        assert False
    except RestorePreflightFailed as exc:
        assert any(r.name == "orjinal_instance_yok" and not r.passed for r in exc.report.results)
    op = session.get(RestoreOp, op_id)
    assert op.state == "FAILED"
    assert "orjinal_instance_yok" in op.error


def test_apply_rejects_non_planned(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = session.get(RestoreOp, op_id)
    op.state = "DONE"
    session.commit()
    try:
        svc.apply(op_id)
        assert False
    except RestorePlanError as exc:
        assert "yeniden plan" in str(exc)


def test_apply_rejects_deleted_point(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    session.delete(point)
    session.commit()
    try:
        svc.apply(op_id)
        assert False
    except RestorePlanError as exc:
        assert "yeniden plan" in str(exc)
    op = session.get(RestoreOp, op_id)
    assert op.state == "FAILED"
    assert op.error == "restore point silinmis"
    assert op.finished_at is not None


def test_apply_rejects_missing_op(session) -> None:
    svc = _service(session)
    try:
        svc.apply(999)
        assert False
    except RestorePlanError as exc:
        assert "restore op yok" in str(exc)


def test_apply_requires_gateway(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    svc = RestoreService(session, None, lambda: FakeRestoreGateway())
    try:
        svc.apply(op_id)
        assert False
    except RestorePlanError as exc:
        assert "gateway gerekli" in str(exc)
    op = session.get(RestoreOp, op_id)
    assert op.state == "PLANNED"


def test_apply_corrupt_plan_marks_failed(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = session.get(RestoreOp, op_id)
    op.plan = {"strategy": "rebuild"}
    session.commit()
    try:
        svc.apply(op_id)
        assert False
    except RestorePlanError as exc:
        assert "plan verisi bozuk" in str(exc)
    op = session.get(RestoreOp, op_id)
    assert op.state == "FAILED"
    assert op.error == "plan verisi bozuk — yeniden plan"
    assert op.finished_at is not None


def test_show_reads_op(session) -> None:
    manifest = make_manifest()
    point = _seed_point(session, manifest)
    svc = _service(session)
    op_id = svc.plan(point.id, RestoreOptions(strategy=RestoreStrategy.REBUILD))
    op = svc.show(op_id)
    assert op.id == op_id
    assert op.state == "PLANNED"
