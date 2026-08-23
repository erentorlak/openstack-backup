from sqlalchemy import select

from osbak.discovery.gateway import ProjectInfo, ServerInfo, VolumeAttachment, VolumeInfo
from osbak.discovery.service import DiscoveryService
from osbak.models import Instance, Project, VolumeRef
from tests.fake_gateway import FakeGateway


def _fake_gateway() -> FakeGateway:
    return FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="proj-a")],
        servers={
            "pid-1": [
                ServerInfo(id="i-1", name="web-1", project_id="pid-1", status="ACTIVE", flavor_id="f-1")
            ]
        },
        volumes={
            "pid-1": [
                VolumeInfo(
                    id="v-root",
                    name="root",
                    size=10,
                    volume_type="ssd",
                    status="in-use",
                    bootable=True,
                    host="node1@rbd-1#pool-a",
                    project_id="pid-1",
                    attachments=(VolumeAttachment(server_id="i-1", device="/dev/vda",
                                                  attachment_id="a-1", volume_id="v-root"),),
                ),
                VolumeInfo(
                    id="v-data",
                    name="data",
                    size=20,
                    volume_type="ssd",
                    status="in-use",
                    bootable=False,
                    host="node1@rbd-1#pool-a",
                    project_id="pid-1",
                    attachments=(VolumeAttachment(server_id="i-1", device="/dev/vdb",
                                                  attachment_id="a-2", volume_id="v-data"),),
                ),
            ]
        },
    )


def test_refresh_creates_rows(session) -> None:
    service = DiscoveryService(_fake_gateway())
    result = service.refresh(session, project_ids=["pid-1"])
    assert result.projects == 1
    assert result.instances == 1
    assert result.volumes == 2
    project = session.scalar(select(Project).where(Project.keystone_project_id == "pid-1"))
    instance = session.scalar(select(Instance).where(Instance.instance_uuid == "i-1"))
    assert project is not None and instance is not None
    refs = session.scalars(select(VolumeRef).where(VolumeRef.instance_id == instance.id)).all()
    by_vol = {r.volume_uuid: r for r in refs}
    assert by_vol["v-root"].pool == "pool-a"
    assert by_vol["v-root"].boot_index == 0
    assert by_vol["v-root"].backend == "rbd-1"
    assert by_vol["v-data"].boot_index == -1


def test_refresh_is_idempotent(session) -> None:
    gateway = _fake_gateway()
    service = DiscoveryService(gateway)
    first = service.refresh(session, project_ids=["pid-1"])
    second = service.refresh(session, project_ids=["pid-1"])
    assert first == second
    assert len(session.scalars(select(Instance)).all()) == 1
    assert len(session.scalars(select(VolumeRef)).all()) == 2
