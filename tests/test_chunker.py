from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, Extent, chunk_hash, split_bytes


def test_chunk_hash_blake2b_64hex() -> None:
    h = chunk_hash(b"hello")
    assert len(h) == 64
    assert h == chunk_hash(b"hello")
    assert h != chunk_hash(b"hellp")


def test_split_bytes_empty() -> None:
    assert split_bytes(b"", 0) == []


def test_split_bytes_smaller_than_block() -> None:
    data = b"a" * 10
    extents = split_bytes(data, 0)
    assert len(extents) == 1
    assert extents[0].offset == 0 and extents[0].length == 10 and extents[0].exists is True


def test_split_bytes_exact_multiple() -> None:
    bs = DEFAULT_BLOCK_SIZE
    data = b"b" * (bs * 2)
    extents = split_bytes(data, 0)
    assert [e.length for e in extents] == [bs, bs]
    assert extents[1].offset == bs


def test_split_bytes_with_start_offset() -> None:
    data = b"c" * 100
    extents = split_bytes(data, 500, block_size=64)
    assert extents[0].offset == 500
    assert [e.length for e in extents] == [64, 36]
