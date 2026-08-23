from osbak.mover.chunker import chunk_hash
from tests.memory_store import MemoryChunkStore


def test_memory_store_roundtrip() -> None:
    store = MemoryChunkStore()
    data = b"payload"
    h = chunk_hash(data)
    assert store.exists(h) is False
    store.put(h, data)
    assert store.exists(h) is True
    assert store.get(h) == data
    assert store.get("nope") is None


def test_fake_source_contract() -> None:
    from osbak.mover.chunker import Extent
    from tests.fake_source import FakeVolumeSource

    src = FakeVolumeSource(
        [Extent(offset=0, length=3, exists=True)],
        {0: b"abc"},
    )
    assert src.iter_extents()[0].offset == 0
    assert src.read(src.iter_extents()[0]) == b"abc"
