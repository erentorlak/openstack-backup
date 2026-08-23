from __future__ import annotations

from osbak.mover.chunker import Extent
from osbak.mover.source import VolumeSource


class FakeVolumeSource(VolumeSource):
    """extent+data sözlüğünden beslenen test kaynağı."""

    def __init__(self, extents: list[Extent], data: dict[int, bytes]) -> None:
        self._extents = extents
        self._data = data

    def iter_extents(self) -> list[Extent]:
        return list(self._extents)

    def read(self, extent: Extent) -> bytes:
        return self._data[extent.offset]
