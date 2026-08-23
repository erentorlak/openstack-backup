import importlib.util
import pytest

from osbak.providers.base import ProviderUnavailable
from osbak.providers.ceph import CephProvider, snap_name


def test_snap_name_format() -> None:
    assert snap_name("i-1", "20260823T120000Z", 1) == "bkp-i-1-20260823T120000Z-1"
    assert snap_name("i-2", "20260823T120000Z", 3).startswith("bkp-i-2-")


def test_ceph_provider_unavailable_without_rados(monkeypatch: pytest.MonkeyPatch) -> None:
    def _none(name: str):
        return None

    monkeypatch.setattr(importlib.util, "find_spec", _none)
    with pytest.raises(ProviderUnavailable):
        CephProvider()


def test_ceph_provider_capabilities() -> None:
    caps = CephProvider.capabilities
    assert caps.can_snapshot is True
    assert caps.native_diff is True
    assert caps.data_path == "rbd"


def test_ceph_provider_constructs_if_rados_spec_present(monkeypatch: pytest.MonkeyPatch) -> None:
    def _present(name: str):
        return types.SimpleNamespace()

    import types

    monkeypatch.setattr(importlib.util, "find_spec", _present)
    provider = CephProvider()
    assert provider.name == "ceph"
