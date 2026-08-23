import pytest
from sqlalchemy import select

from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, Extent, chunk_hash
from osbak.mover.service import ExportService, ExportStats
from osbak.models import Chunk, RestorePoint, VolumeBackup, VolumeChunkMap
from tests.fake_source import FakeVolumeSource
from tests.memory_store import MemoryChunkStore


def test_memory_store_roundtrip() -> None:
    store = MemoryChunkStore()
    data = b"payload"
    h = chunk_hash(data)
    assert store.exists(h) is False
    store.put(h, data)
    assert store.exists(h) is True
    assert store.get(h) == data
    assert store.get("nope") is None


def test_fake_source_contract() -> None:
    src = FakeVolumeSource(
        [Extent(offset=0, length=3, exists=True)],
        {0: b"abc"},
    )
    assert src.iter_extents()[0].offset == 0
    assert src.read(src.iter_extents()[0]) == b"abc"


def _restore_point(session) -> RestorePoint:
    rp = RestorePoint(kind="snapshot", instance_id=1, manifest={}, status="active")
    session.add(rp)
    session.flush()
    return rp


def _volume_backup(session, tier: str = "t0"):
    rp = _restore_point(session)
    vb = VolumeBackup(restore_point_id=rp.id, volume_ref_id=None,
                      snapshot_ref="pool-a/v-root@s-1", tier=tier, object_manifest={})
    session.add(vb)
    session.flush()
    return vb


def test_export_single_block(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    data = b"a" * 100
    src = FakeVolumeSource([Extent(offset=0, length=100, exists=True)], {0: data})
    stats = ExportService(store).export_volume(session, vb, src)
    assert isinstance(stats, ExportStats)
    assert stats.chunks_new == 1 and stats.chunks_existing == 0
    assert stats.bytes_written == 100 and stats.extents_skipped == 0
    assert vb.tier == "t1"
    c = session.scalar(select(Chunk))
    assert c is not None and c.refcount == 1
    assert store.exists(c.chunk_hash)


def test_export_dedupes_second_backup(session) -> None:
    store = MemoryChunkStore()
    data = b"b" * 100
    src = FakeVolumeSource([Extent(offset=0, length=100, exists=True)], {0: data})
    vb1 = _volume_backup(session)
    ExportService(store).export_volume(session, vb1, src)
    vb2 = _volume_backup(session)
    stats2 = ExportService(store).export_volume(session, vb2, src)
    assert stats2.chunks_new == 0 and stats2.chunks_existing == 1
    assert len(session.scalars(select(Chunk)).all()) == 1  # tek blok, refcount 2
    assert session.scalar(select(Chunk)).refcount == 2


def test_export_skips_zero_extents(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    src = FakeVolumeSource(
        [Extent(offset=0, length=50, exists=False), Extent(offset=50, length=50, exists=True)],
        {50: b"z" * 50},
    )
    stats = ExportService(store).export_volume(session, vb, src)
    assert stats.extents_skipped == 1
    assert stats.chunks_new == 1
    assert len(session.scalars(select(VolumeChunkMap)).all()) == 1
    assert session.scalar(select(VolumeChunkMap)).offset_bytes == 50


def test_export_rejects_non_t0(session) -> None:
    vb = _volume_backup(session, tier="t1")
    service = ExportService(MemoryChunkStore())
    with pytest.raises(ValueError):
        service.export_volume(session, vb, FakeVolumeSource([], {}))


def test_export_splits_large_extent(session) -> None:
    bs = DEFAULT_BLOCK_SIZE
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    data = b"c" * (bs + 100)
    src = FakeVolumeSource([Extent(offset=0, length=len(data), exists=True)], {0: data})
    stats = ExportService(store).export_volume(session, vb, src)
    assert stats.chunks_new == 2
    assert len(session.scalars(select(VolumeChunkMap)).all()) == 2


def test_export_rollback_on_error(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()

    class _BadSource:
        def iter_extents(self):
            return [Extent(offset=0, length=10, exists=True)]

        def read(self, extent):
            raise RuntimeError("read failed")

    with pytest.raises(RuntimeError):
        ExportService(store).export_volume(session, vb, _BadSource())
    assert len(session.scalars(select(Chunk)).all()) == 0  # kısmi satır yok
    assert vb.tier == "t0"  # değişmedi
