from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderUnavailable(Exception):
    """Provider missing or not installed (missing cephx/rados/ONTAP dependency)."""


@dataclass(frozen=True)
class ProviderCapabilities:
    can_snapshot: bool
    native_diff: bool
    data_path: str
    rollback: frozenset[str] = field(default_factory=frozenset)
    source_kind: str = ""


@dataclass(frozen=True)
class SnapshotTarget:
    image: str
    pool: str
    project_id: str
    instance_id: str


@dataclass(frozen=True)
class SnapshotRef:
    provider: str
    image: str
    pool: str
    snapshot: str
    created_at: str


class SnapshotProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def snapshot(self, target: SnapshotTarget, name_prefix: str) -> SnapshotRef: ...

    def delete(self, ref: SnapshotRef) -> None: ...
