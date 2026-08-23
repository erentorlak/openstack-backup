from __future__ import annotations

import importlib.util
from typing import Protocol

from osbak.mover.chunker import Extent
from osbak.providers.base import ProviderUnavailable


class VolumeSource(Protocol):
    def iter_extents(self) -> list[Extent]: ...

    def read(self, extent: Extent) -> bytes: ...


class CephRbdSource:
    """Live source based on rbd diff --from-snap. OUT of unit-test scope (live env).

    `__init__` only probes find_spec("rados"); the import happens lazily at call time
    (iter_extents/read) via importlib.import_module.
    """

    def __init__(
        self,
        pool: str,
        image: str,
        snapshot: str,
        base_snapshot: str | None = None,
        block_size: int = 4 * 1024 * 1024,
    ) -> None:
        if importlib.util.find_spec("rados") is None:
            raise ProviderUnavailable("rados python binding kurulu değil (osbak[ceph])")
        self._pool = pool
        self._image = image
        self._snapshot = snapshot
        self._base_snapshot = base_snapshot
        self._resolved: list[Extent] | None = None

    def iter_extents(self) -> list[Extent]:
        # Live: rbd diff --whole-object --from-snap <base> -> offset/length/zero
        # -> exists=(data) Extent. Exact command finalized during live verification.
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def read(self, extent: Extent) -> bytes:
        raise NotImplementedError("canlı ortamda doğrulanacak")
