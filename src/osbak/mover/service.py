from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, Extent, chunk_hash, split_bytes
from osbak.mover.source import VolumeSource
from osbak.mover.store import ChunkStore
from osbak.models import Chunk, VolumeBackup, VolumeChunkMap


@dataclass(frozen=True)
class ExportStats:
    chunks_new: int = 0
    chunks_existing: int = 0
    bytes_written: int = 0
    extents_skipped: int = 0


class ExportService:
    def __init__(
        self,
        store: ChunkStore,
        block_size: int = DEFAULT_BLOCK_SIZE,
    ) -> None:
        self._store = store
        self._block_size = block_size

    def export_volume(
        self,
        session: Session,
        volume_backup: VolumeBackup,
        source: VolumeSource,
    ) -> ExportStats:
        if volume_backup.tier != "t0":
            raise ValueError("yalnızca T0 volume backup'ı export edilebilir")

        stats = ExportStats()
        manifest: list[dict] = []
        try:
            for extent in source.iter_extents():
                if not extent.exists:
                    stats = ExportStats(
                        stats.chunks_new, stats.chunks_existing,
                        stats.bytes_written, stats.extents_skipped + 1,
                    )
                    continue
                data = source.read(extent)
                for part in split_bytes(data, extent.offset, self._block_size):
                    i = part.offset - extent.offset
                    part_data = data[i : i + part.length]
                    h = chunk_hash(part_data)
                    chunk_row = session.scalar(
                        select(Chunk).where(Chunk.chunk_hash == h)
                    )
                    if chunk_row is None:
                        self._store.put(h, part_data)
                        session.add(Chunk(chunk_hash=h, size_bytes=len(part_data), refcount=1))
                        stats = ExportStats(
                            stats.chunks_new + 1, stats.chunks_existing,
                            stats.bytes_written + len(part_data), stats.extents_skipped,
                        )
                    else:
                        chunk_row.refcount += 1
                        stats = ExportStats(
                            stats.chunks_new, stats.chunks_existing + 1,
                            stats.bytes_written, stats.extents_skipped,
                        )
                    session.add(
                        VolumeChunkMap(
                            volume_backup_id=volume_backup.id,
                            chunk_hash=h,
                            offset_bytes=part.offset,
                            length=part.length,
                        )
                    )
                    manifest.append({"hash": h, "offset": part.offset, "length": part.length})
            volume_backup.tier = "t1"
            volume_backup.object_manifest = manifest
            session.commit()
        except Exception:
            session.rollback()
            raise
        return stats
