from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, chunk_hash, split_bytes
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

        chunks_new = chunks_existing = bytes_written = extents_skipped = 0
        manifest: list[dict] = []
        try:
            for extent in source.iter_extents():
                if not extent.exists:
                    extents_skipped += 1
                    continue
                data = source.read(extent)
                for part in split_bytes(data, extent.offset, self._block_size):
                    if not (extent.offset <= part.offset < extent.offset + len(data)):
                        raise AssertionError("split_bytes offset invariant broken")
                    i = part.offset - extent.offset
                    part_data = data[i : i + part.length]
                    h = chunk_hash(part_data)
                    chunk_row = session.scalar(
                        select(Chunk).where(Chunk.chunk_hash == h)
                    )
                    if chunk_row is None:
                        self._store.put(h, part_data)
                        session.add(Chunk(chunk_hash=h, size_bytes=len(part_data), refcount=1))
                        # autoflush=False means scalar() can't see the pending INSERT; flush()
                        # makes the row visible in the same transaction -> a repeated hash in
                        # the same export bumps refcount instead of hitting the UNIQUE index.
                        session.flush()
                        chunks_new += 1
                        bytes_written += len(part_data)
                    else:
                        chunk_row.refcount += 1
                        chunks_existing += 1
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
        return ExportStats(
            chunks_new=chunks_new,
            chunks_existing=chunks_existing,
            bytes_written=bytes_written,
            extents_skipped=extents_skipped,
        )
