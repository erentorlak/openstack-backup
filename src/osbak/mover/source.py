from __future__ import annotations

import importlib.util
from typing import Protocol

from osbak.mover.chunker import Extent
from osbak.providers.base import ProviderUnavailable


class VolumeSource(Protocol):
    def iter_extents(self) -> list[Extent]: ...

    def read(self, extent: Extent) -> bytes: ...


class CephRbdSource:
    """rbd diff --from-snap tabanlı canlı kaynak. Birim test DIŞI (canlı ortam).

    `__init__` yalnızca find_spec("rados") probe'u yapar; import'u çağrı anında
    (iter_extents/read) importlib.import_module ile gerçekleşir.
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
        # Canlı: rbd diff --whole-object --from-snap <base> → offset/length/zero
        # → exists=(data) Extent. Kesin komut canlı doğrulamada netleşir.
        raise NotImplementedError("canlı ortamda doğrulanacak")

    def read(self, extent: Extent) -> bytes:
        raise NotImplementedError("canlı ortamda doğrulanacak")
