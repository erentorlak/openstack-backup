from __future__ import annotations

from osbak.mover.store import ChunkStore


class MemoryChunkStore(ChunkStore):
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, chunk_hash: str, data: bytes) -> None:
        self._data[chunk_hash] = data

    def get(self, chunk_hash: str) -> bytes | None:
        return self._data.get(chunk_hash)

    def exists(self, chunk_hash: str) -> bool:
        return chunk_hash in self._data
