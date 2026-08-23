from __future__ import annotations

import hashlib
from dataclasses import dataclass

DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024


@dataclass(frozen=True)
class Extent:
    offset: int
    length: int
    exists: bool = True


def chunk_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def split_bytes(
    data: bytes,
    start_offset: int,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> list[Extent]:
    extents: list[Extent] = []
    for i in range(0, len(data), block_size):
        chunk = data[i : i + block_size]
        extents.append(Extent(offset=start_offset + i, length=len(chunk), exists=True))
    return extents
