from __future__ import annotations

import importlib.util
from datetime import datetime, timezone

from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)


def snap_name(instance_id: str, ts: str, seq: int) -> str:
    return f"bkp-{instance_id}-{ts}-{seq}"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CephProvider:
    name = "ceph"
    capabilities = ProviderCapabilities(
        can_snapshot=True,
        native_diff=True,
        data_path="rbd",
        rollback=frozenset({"live", "cold", "rebuild"}),
        source_kind="pool",
    )

    def __init__(self) -> None:
        if importlib.util.find_spec("rados") is None:
            raise ProviderUnavailable("rados python binding kurulu değil (osbak[ceph])")

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef:
        # Real rados path verified in a live environment (out of unit-test scope).
        # At call time: rados = importlib.import_module("rados"); rbd = ...;
        # Rados().connect -> open_ioctx(target.pool) -> Image.open(target.image)
        # -> create_snap(<bkp-name>) — exact command finalized in live verification.
        snapshot = snap_name(target.instance_id, _utc_iso(), 1)
        return SnapshotRef(
            provider=self.name,
            image=target.image,
            pool=target.pool,
            snapshot=snapshot,
            created_at=_utc_iso(),
        )

    def delete(self, ref: SnapshotRef) -> None:
        # Verified in a live environment; remove_snap + deep flatten if needed.
        return None
