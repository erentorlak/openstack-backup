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
