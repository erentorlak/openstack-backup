import pytest
from sqlalchemy import select

from osbak.discovery.gateway import FlavorInfo, ProjectInfo, ServerInfo, VolumeAttachment, VolumeInfo
from osbak.models import Instance, Project, RestorePoint, VolumeBackup, VolumeRef
from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)
from osbak.snapshot.service import SnapshotOptions, SnapshotPreflightFailed, SnapshotService, SnapshotResult
from tests.fake_gateway import FakeGateway


class _RecordingProvider:
    name = "test"
    capabilities = ProviderCapabilities(
        can_snapshot=True, native_diff=False, data_path="rbd",
        rollback=frozenset(), source_kind="pool",
    )
    snapshot_calls: list[str] = []
    delete_calls: list[str] = []

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef:
        self.snapshot_calls.append(target.image)
        return SnapshotRef(provider=self.name, image=target.image, pool=target.pool,
                           snapshot="s-1", created_at="2026-01-01T00:00:00Z")

    def delete(self, ref: SnapshotRef) -> None:
        self.delete_calls.append(ref.image)


def _server():
    return ServerInfo(id="i-1", name="web", project_id="pid-1", status="ACTIVE", flavor_id="f-1")


def _volume():
    return VolumeInfo(
        id="v-root", name="root", size=10, volume_type="ssd", status="in-use",
        bootable=True, host="node@rbd-1#pool-a", project_id="pid-1",
        attachments=(VolumeAttachment(server_id="i-1", device="/dev/vda",
                                      attachment_id="a-1", volume_id="v-root"),),
    )


def _gateway(server, volume):
    return FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
        volumes={"pid-1": [volume]},
        flavors={"f-1": FlavorInfo(id="f-1", name="m", vcpus=1, ram=1, disk=10,
                                   ephemeral=0, swap=0, is_public=True)},
    )


def _factory(driver: str):
    if driver == "rbd-1":
        return _RecordingProvider()
    raise ProviderUnavailable(f"bilinmeyen driver: {driver}")


def _seed_catalog(session) -> None:
    project = Project(keystone_project_id="pid-1", enabled=True)
    session.add(project)
    session.flush()
    session.add(Instance(instance_uuid="i-1", project_id=project.id))
    session.commit()


def test_snapshot_writes_restore_point(session) -> None:
    _RecordingProvider.snapshot_calls = []
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    result = SnapshotService(gw, _factory).snapshot_instance(
        session, "i-1", SnapshotOptions(require_consistent=False)
    )
    assert isinstance(result, SnapshotResult)
    assert result.volumes_snapshotted == 1
    assert result.consistent is False
    assert _RecordingProvider.snapshot_calls == ["v-root"]
    rp = session.scalar(select(RestorePoint).where(RestorePoint.id == result.restore_point_id))
    assert rp is not None and rp.kind == "snapshot"
    assert rp.manifest["instance"]["id"] == "i-1"
    vbs = session.scalars(select(VolumeBackup).where(VolumeBackup.restore_point_id == rp.id)).all()
    assert len(vbs) == 1
    assert vbs[0].tier == "t0"
    assert vbs[0].snapshot_ref == "pool-a/v-root@s-1"


def test_snapshot_quiesce_and_teardown(session) -> None:
    _RecordingProvider.snapshot_calls = []
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    SnapshotService(gw, _factory).snapshot_instance(
        session, "i-1", SnapshotOptions(require_consistent=True)
    )
    assert gw._quiesced == ["i-1"]
    assert gw._unquiesced == ["i-1"]


def test_snapshot_quiesce_teardown_on_provider_error(session) -> None:
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)

    class _BoomProvider(_RecordingProvider):
        def snapshot(self, target, name_prefix):
            raise RuntimeError("snapshot failed")

    def factory(driver):
        return _BoomProvider()

    service = SnapshotService(gw, factory)
    with pytest.raises(RuntimeError):
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=True))
    assert gw._unquiesced == ["i-1"]
    assert len(session.scalars(select(RestorePoint)).all()) == 0  # rollback: kısmi kayıt yok


class _QuiesceFailsGateway(FakeGateway):
    def quiesce_guest(self, server_id: str) -> None:
        self._quiesced.append(server_id)
        raise RuntimeError("quiesce timeout")

    def unquiesce_guest(self, server_id: str) -> None:
        self._unquiesced.append(server_id)


def test_snapshot_unquiesce_on_quiesce_failure(session) -> None:
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _QuiesceFailsGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
        volumes={"pid-1": [volume]},
        flavors={"f-1": FlavorInfo(id="f-1", name="m", vcpus=1, ram=1, disk=10,
                                   ephemeral=0, swap=0, is_public=True)},
    )
    service = SnapshotService(gw, _factory)
    with pytest.raises(RuntimeError):
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=True))
    assert gw._quiesced == ["i-1"]
    assert gw._unquiesced == ["i-1"]  # teardown her zaman


def test_snapshot_links_volume_ref(session) -> None:
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    _RecordingProvider.snapshot_calls = []
    project = Project(keystone_project_id="pid-1", enabled=True)
    session.add(project)
    session.flush()
    session.add(Instance(instance_uuid="i-1", project_id=project.id))
    session.flush()
    inst = session.scalar(select(Instance).where(Instance.instance_uuid == "i-1"))
    session.add(VolumeRef(instance_id=inst.id, volume_uuid="v-root", boot_index=0,
                          size_gb=10, volume_type="ssd", backend="rbd", pool="pool-a"))
    session.commit()
    result = SnapshotService(gw, _factory).snapshot_instance(
        session, "i-1", SnapshotOptions(require_consistent=False)
    )
    vb = session.scalar(select(VolumeBackup).where(
        VolumeBackup.restore_point_id == result.restore_point_id))
    assert vb is not None and vb.volume_ref_id is not None


def test_snapshot_preflight_missing_instance(session) -> None:
    gw = FakeGateway(projects=[ProjectInfo(id="pid-1", name="a")], servers={"pid-1": []})
    service = SnapshotService(gw, _factory)
    with pytest.raises(SnapshotPreflightFailed):
        service.snapshot_instance(session, "nope", SnapshotOptions(require_consistent=False))


def test_snapshot_unknown_driver_fails(session) -> None:
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    service = SnapshotService(gw, lambda driver: (_ for _ in ()).throw(ProviderUnavailable(driver)))
    with pytest.raises(SnapshotPreflightFailed):
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=False))


def test_snapshot_fails_without_catalog_instance(session) -> None:
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    _RecordingProvider.snapshot_calls = []
    service = SnapshotService(gw, _factory)
    with pytest.raises(SnapshotPreflightFailed) as exc:
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=False))
    assert _RecordingProvider.snapshot_calls == []  # snapshot hiç yapılmadı
    assert "katalogda instance yok" in str(exc.value)


def test_snapshot_cleans_refs_on_manifest_build_failure(session) -> None:
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    _RecordingProvider.delete_calls = []

    class _BoomBuilder:
        def build(self, project_id, server):
            raise RuntimeError("manifest build failed")

    with pytest.raises(RuntimeError):
        SnapshotService(gw, _factory, manifest_builder=_BoomBuilder()).snapshot_instance(
            session, "i-1", SnapshotOptions(require_consistent=True)
        )
    assert _RecordingProvider.delete_calls == ["v-root"]  # snapshot ref temizlendi
    assert gw._unquiesced == ["i-1"]  # teardown her zaman
    assert len(session.scalars(select(RestorePoint)).all()) == 0  # kısmi kayıt rollback


def test_snapshot_preflight_error_carries_cause(session) -> None:
    _seed_catalog(session)
    server, volume = _server(), _volume()
    gw = _gateway(server, volume)
    service = SnapshotService(gw, lambda driver: (_ for _ in ()).throw(ProviderUnavailable(driver)))
    with pytest.raises(SnapshotPreflightFailed) as exc:
        service.snapshot_instance(session, "i-1", SnapshotOptions(require_consistent=False))
    assert "provider yok" in str(exc.value)


def test_snapshot_cleans_created_refs_on_partial_failure(session) -> None:
    _seed_catalog(session)
    server = _server()
    v_root = _volume()
    v_data = VolumeInfo(
        id="v-data", name="data", size=50, volume_type="ssd", status="in-use",
        bootable=False, host="node@rbd-2#pool-b", project_id="pid-1",
        attachments=(VolumeAttachment(server_id="i-1", device="/dev/vdb",
                                      attachment_id="a-2", volume_id="v-data"),),
    )
    gw = FakeGateway(
        projects=[ProjectInfo(id="pid-1", name="a")],
        servers={"pid-1": [server]},
        volumes={"pid-1": [v_root, v_data]},
        flavors={"f-1": FlavorInfo(id="f-1", name="m", vcpus=1, ram=1, disk=10,
                                   ephemeral=0, swap=0, is_public=True)},
    )
    _RecordingProvider.delete_calls = []

    class _BoomProvider(_RecordingProvider):
        def snapshot(self, target, name_prefix):
            raise RuntimeError("snapshot failed")

    def factory(driver: str):
        if driver == "rbd-1":
            return _RecordingProvider()
        if driver == "rbd-2":
            return _BoomProvider()
        raise ProviderUnavailable(f"bilinmeyen driver: {driver}")

    with pytest.raises(RuntimeError):
        SnapshotService(gw, factory).snapshot_instance(
            session, "i-1", SnapshotOptions(require_consistent=True)
        )
    assert gw._unquiesced == ["i-1"]
    assert _RecordingProvider.delete_calls == ["v-root"]
    assert len(session.scalars(select(RestorePoint)).all()) == 0  # kısmi kayıt yok
