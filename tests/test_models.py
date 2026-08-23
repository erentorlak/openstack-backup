from sqlalchemy import inspect

from sqlalchemy import create_engine

from osbak.db import init_db, make_session_factory
from osbak.models import Instance, Project, VolumeRef


def test_schema_has_all_tables() -> None:
    engine = create_engine("sqlite://")
    init_db(engine)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "projects", "instances", "volume_refs", "restore_points",
        "volume_backups", "chunks", "volume_chunk_map",
        "policies", "jobs", "restore_ops",
    }
    assert expected <= tables


def test_roundtrip_project_instance_volume() -> None:
    engine = create_engine("sqlite://")
    init_db(engine)
    session = make_session_factory(engine)()
    try:
        project = Project(keystone_project_id="pid-1", enabled=True)
        session.add(project)
        session.flush()
        inst = Instance(instance_uuid="i-1", project_id=project.id)
        session.add(inst)
        session.flush()
        session.add(
            VolumeRef(
                instance_id=inst.id,
                volume_uuid="v-1",
                boot_index=0,
                size_gb=10,
                volume_type="ssd",
                backend="rbd",
                pool="pool-a",
            )
        )
        session.commit()
        assert session.get(Instance, inst.id).volumes[0].pool == "pool-a"
    finally:
        session.close()
        engine.dispose()
