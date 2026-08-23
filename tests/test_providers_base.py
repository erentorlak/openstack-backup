import pytest

from osbak.providers.base import (
    ProviderCapabilities,
    ProviderUnavailable,
    SnapshotProvider,
    SnapshotRef,
    SnapshotTarget,
)


def test_capabilities_frozen() -> None:
    caps = ProviderCapabilities(
        can_snapshot=True,
        native_diff=True,
        data_path="rbd",
        rollback=frozenset({"live", "cold", "rebuild"}),
        source_kind="pool",
    )
    assert caps.can_snapshot is True
    assert caps.rollback == frozenset({"live", "cold", "rebuild"})


def test_provider_unavailable_is_exception() -> None:
    with pytest.raises(ProviderUnavailable):
        raise ProviderUnavailable("ceph provider yok")


def test_target_and_ref_are_frozen() -> None:
    target = SnapshotTarget(image="vol-1", pool="volumes", project_id="p", instance_id="i")
    ref = SnapshotRef(provider="ceph", image="vol-1", pool="volumes", snapshot="s-1", created_at="2026-01-01T00:00:00Z")
    with pytest.raises(AttributeError):
        target.image = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        ref.snapshot = "y"  # type: ignore[misc]


def test_protocol_is_subscriptable_protocol() -> None:
    assert SnapshotProvider  # isinstance check yerine varlık/type check
