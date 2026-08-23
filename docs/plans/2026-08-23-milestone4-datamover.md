# Plan 4: Data Mover (chunk+hash) + T1 offload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** T1 offload çekirdeğini inşa et: volume verisini block'lara böl, content-addressed hash'le (blake2b, 4MiB), bir chunk store'a yaz (T1), `chunks`/`volume_chunk_map` katalog satırlarıyla refcount dedup'u yönet, `VolumeBackup.tier`'ı T0→T1'e taşı. `VolumeSource` soyutlaması üzerinden Ceph (rbd diff/live) ve NetApp (future) kaynaklarına hazır.

**Architecture:** `osbak.mover.chunker` (safe: `Extent`, `chunk_hash`, split) → `osbak.mover.store` (`ChunkStore` Protocol + `S3ChunkStore` live-thin) → `osbak.mover.source` (`VolumeSource` Protocol + `CephRbdSource` live-lazy) → `osbak.mover.service.ExportService.export_volume(session, volume_backup_id, source, store, block_size)` (chunk → dedup → DB → tier). Canlı rados/boto3 kod yolları birim test DIŞI (live-görev); S3ChunkStore, MemoryChunkStore (tests/) ile, source FakeVolumeSource (tests/) ile test edilir.

**Tech Stack:** Python ≥3.10, mevcut osbak, boto3 (live S3, opsiyonel), pytest. Yeni zorunlu bağımlılık: **Hayır** (boto3 `osbak[t1]` extra olarak canlı kurulumda).

**Spec:** `docs/specs/2026-08-23-osbak-architecture.md` (§3 T1, §6 chunk model, §7.1 adım 5 EXPORT, §9 provider diff=ipucu/hash=doğruluk) + ADR-001/002.

## Global Constraints

- **Fallback kuralı:** YOK: çok-anahtar okuma yok, geniş `except Exception` yok. Diff = ipucu, hash = doğruluk (chunk hash'i dedup kararının TEK kaynağıdır; store.exists/hash karşılaştırmasıyla doğrulanır — "diff'e güven, hash'le doğrula").
- Chunk hash: `hashlib.blake2b(data, digest_size=32).hexdigest()` → 64 hex char (models.Chunk.chunk_hash String(64) ile uyumlu). Block boyutu default `4 * 1024 * 1024` (4MiB).
- `volume_chunk_map` satırları (volume_backup_id, chunk_hash, offset_bytes, length) yazılır; aynı hash zaten chunks'ta varsa refcount++ (yeni upload yok), yoksa chunks satırı oluştur + store.put (dedup).
- `VolumeBackup.tier` "t1"e taşınır; `object_manifest` = JSON listesi `[{"hash", "offset", "length"}, ...]` (katalog kaybı durumunda manifestin portability'si; T2 Plan 8'de).
- `ExportService.export_volume` çağrısı: verileri source'tan extent bazlı okur, bloklar halinde işler, store+database senkrone. Hata durumunda `session.rollback()` (kısmi chunk/refcount satırı kalmaz) — görünür, sessiz değil.
- Gerçek S3/Ceph canlı kod yolları (S3ChunkStore, CephRbdSource) birim test listesi DIŞI — canlı ortam doğrulaması (NOTES). Bunların yerine saf çekirdek (chunker/dedup/db yazımı) MemoryChunkStore + FakeVolumeSource ile test edilir.
- No live infra; tests: test_chunker.py, test_store.py (MemoryChunkStore sadece tests/), test_export.py.
- `models.Chunk.chunk_hash` PK kolonu adı "hash" (attribute chunk_hash); `VolumeChunkMap(chunk_hash FK → chunks.hash)`.
- Manifest/offload ayrımı: bu plan VolumeBackup (tür=backup değil, offload) — snapshot → export akışını Plan 3'ün SnapshotService'i çağırır (engine wiring sonraki milestone). Bu plan yalnızca ExportService.

## File Structure

```
src/osbak/mover/__init__.py
src/osbak/mover/chunker.py        # Extent, chunk_hash, split_blobs
src/osbak/mover/store.py          # ChunkStore Protocol + S3ChunkStore (live-thin)
src/osbak/mover/source.py         # VolumeSource Protocol + CephRbdSource (live-lazy)
src/osbak/mover/service.py        # ExportService + ExportStats
src/osbak/mover/NOTES.md
tests/test_chunker.py
tests/test_export.py
tests/memory_store.py             # MemoryChunkStore (test yardımcı)
tests/fake_source.py              # FakeVolumeSource (test yardımcı)
```

Bu plana CLI/engine wiring DAHİL DEĞİL (Plan 7 scheduler/API); oda: export çekirdeği.

---

## Task 1: chunker — Extent model + blake2b chunk_hash + block splitting

**Files:**
- Create: `src/osbak/mover/__init__.py` (boş)
- Create: `src/osbak/mover/chunker.py`
- Create: `tests/test_chunker.py`

**Interfaces:**
- Produces:
  - `DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024`
  - `@dataclass(frozen=True) class Extent: offset: int; length: int; exists: bool`
  - `chunk_hash(data: bytes) -> str` — blake2b digest_size=32 hexdigest (64 chars)
  - `split_bytes(data: bytes, start_offset: int, block_size: int = DEFAULT_BLOCK_SIZE) -> list[Extent]` — data'yı `block_size`'lik parçalara böler; her parça `Extent(offset=start_offset + i*block_size, length=len(chunk), exists=True)`; boş veri → `[]`.

**Semantik:** `exists=False` extent'ler (rbd diff'te zero region / NetApp'te atlanan) upload EDİLMEZ — chunker onları yok sayar, restore sırasında sparse olur. `split_bytes` yalnızca mevcut veriyi böler.

- [ ] **Step 1: Failing test**

`tests/test_chunker.py`:
```python
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
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_chunker.py -v` → FAIL (modül yok).

- [ ] **Step 3: Implement**

`src/osbak/mover/chunker.py`:
```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass

DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024


@dataclass(frozen=True)
class Extent:
    offset: int
    length: int
    exists: bool = True


def chunk_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def split_bytes(
    data: bytes,
    start_offset: int,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> list[Extent]:
    extents: list[Extent] = []
    for i in range(0, len(data), block_size):
        chunk = data[i : i + block_size]
        extents.append(Extent(offset=start_offset + i, length=len(chunk), exists=True))
    return extents
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_chunker.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/mover tests/test_chunker.py
git commit -m "feat: chunker (Extent, blake2b chunk_hash, block split)"
```

---

## Task 2: chunk store — ChunkStore Protocol + S3ChunkStore (live) + MemoryChunkStore (test)

**Files:**
- Create: `src/osbak/mover/store.py`
- Create: `tests/memory_store.py`
- Create: `tests/test_export.py` kapsamında `tests/memory_store.py` import'u (test_export Task 3'te/4'te)

**Interfaces:**
- Produces:
  - `ChunkStore` Protocol:
    ```python
    class ChunkStore(Protocol):
        def put(self, chunk_hash: str, data: bytes) -> None: ...
        def get(self, chunk_hash: str) -> bytes | None: ...
        def exists(self, chunk_hash: str) -> bool: ...
    ```
  - `S3ChunkStore(bucket: str, client: Any) -> None` — boto3 tabanlı; `_key(h) = f"chunk/{h}"`; `put` → `client.put_object(Bucket=bucket, Key=_key(h), Body=data)`; `get` → `client.get_object(...)["Body"].read()` (ClientError → None, dar/anlamlı: 404 = yok); `exists` → try head_object → True, ClientError → False. Live-thin, birim test DIŞI.
  - `MemoryChunkStore` (tests/memory_store.py — TEST ARAÇ, src değil): dict tabanlı, aynı Protocol.

- [ ] **Step 1: Failing test**

`tests/memory_store.py`:
```python
from __future__ import annotations

from osbak.mover.store import ChunkStore


class MemoryChunkStore(ChunkStore):
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, chunk_hash: str, data: bytes) -> None:
        self._data[chunk_hash] = data

    def get(self, chunk_hash: str) -> bytes | None:
        return self._data.get(chunk_hash)

    def exists(self, chunk_hash: str) -> bool:
        return chunk_hash in self._data
```

`tests/test_export.py` (bu görevde yalnızca store davranışı):
```python
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
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_export.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/mover/store.py`:
```python
from __future__ import annotations

from typing import Any, Protocol


class ChunkStore(Protocol):
    def put(self, chunk_hash: str, data: bytes) -> None: ...

    def get(self, chunk_hash: str) -> bytes | None: ...

    def exists(self, chunk_hash: str) -> bool: ...


class S3ChunkStore:
    """boto3 tabanlı canlı T1 deposu. Birim test DIŞI (canlı ortam).

    S3 anahtarı: `chunk/<blake2b>`. Tek hata yakalama: ClientError — 404 yok
    anlamına gelir ve `get/exists` için None/False döner (dar, anlamlı).
    """

    def __init__(self, bucket: str, client: Any) -> None:
        self._bucket = bucket
        self._client = client

    @staticmethod
    def _key(chunk_hash: str) -> str:
        return f"chunk/{chunk_hash}"

    def put(self, chunk_hash: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=self._key(chunk_hash), Body=data
        )

    def get(self, chunk_hash: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(
                Bucket=self._bucket, Key=self._key(chunk_hash)
            )
            return resp["Body"].read()
        except ClientError:
            return None

    def exists(self, chunk_hash: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(
                Bucket=self._bucket, Key=self._key(chunk_hash)
            )
            return True
        except ClientError:
            return False
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_export.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/mover/store.py tests/memory_store.py tests/test_export.py
git commit -m "feat: ChunkStore protocol, S3ChunkStore (live), MemoryChunkStore (test)"
```

---

## Task 3: VolumeSource — source Protocol + FakeVolumeSource (test) + CephRbdSource (live-lazy)

**Files:**
- Create: `src/osbak/mover/source.py`
- Create: `tests/fake_source.py`

**Interfaces:**
- Produces:
  - `VolumeSource` Protocol:
    ```python
    class VolumeSource(Protocol):
        def iter_extents(self) -> list[Extent]: ...
        def read(self, extent: Extent) -> bytes: ...
    ```
    - `iter_extents()`: source'un SAHİP OLDUĞU extents listesi (rbd diff --from-snap sonucu; Ceph'te `exists=False` zero-regions; NetApp'te değişmişse tüm dosya).
    - `read(extent)`: extent'in bytes verisini döner. `iter_extents` ve `read` senkron uyumlu: read yalnızca iter_extents'ten dönen extent'ler için çağrılır.
  - `CephRbdSource(pool, image, snapshot, base_snapshot=None, rados_client=None)` — live-lazy: `rados`/`rbd` importlib.import_module ile çağrı anında; `iter_extents()` → rbd diff --from-snap → Extent listesi; read → ioctx/Image.read. Birim test DIŞI (canlı). Yapı: `__init__` içinde `importlib.util.find_spec("rados") is None → ProviderUnavailable` (CephProvider ile tutarlı).

- [ ] **Step 1: Failing test**

`tests/fake_source.py`:
```python
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
```

`tests/test_export.py` — VolumeSource davranışı (source ayrı test dosyası yok; fake source export testinde kullanılır, bu görevde yalnızca kurulum):
```python
def test_fake_source_contract() -> None:
    from osbak.mover.chunker import Extent
    from tests.fake_source import FakeVolumeSource

    src = FakeVolumeSource(
        [Extent(offset=0, length=3, exists=True)],
        {0: b"abc"},
    )
    assert src.iter_extents()[0].offset == 0
    assert src.read(src.iter_extents()[0]) == b"abc"
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_export.py -v` → FAIL (source modülü yok).

- [ ] **Step 3: Implement**

`src/osbak/mover/source.py`:
```python
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
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_export.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/mover/source.py tests/fake_source.py
git commit -m "feat: VolumeSource protocol, CephRbdSource (live-lazy), FakeVolumeSource"
```

---

## Task 4: ExportService — chunk/dedup/db yazımı/tier taşıma

**Files:**
- Create: `src/osbak/mover/service.py`
- Modify: `tests/test_export.py` (export testleri bu görevde)

**Interfaces:**
- Consumes: `chunker` (Extent, chunk_hash, split_bytes, DEFAULT_BLOCK_SIZE), `store` (ChunkStore), `source` (VolumeSource), `osbak.models` (VolumeBackup, VolumeChunkMap, Chunk), `Session`.
- Produces:
  - `ExportStats(chunks_new: int, chunks_existing: int, bytes_written: int, extents_skipped: int)` — frozen dataclass.
  - `ExportService(store: ChunkStore, block_size: int = DEFAULT_BLOCK_SIZE)`.
  - `export_volume(session, volume_backup: VolumeBackup, source: VolumeSource) -> ExportStats`.

**Davranış sözleşmesi (deterministik, fallback yok):**
1. `volume_backup.tier` "t0" DEĞİLSE deterministik hata (`ValueError("yalnızca T0 volume backup'ı export edilebilir")`) — sesli, sessiz atlama yok.
2. `volume_backup.object_manifest` boş varsayılır; işlem sonunda JSON listesiyle değiştirilir (önceki manifest varsa üzerine yazılır — deterministik; incremental zincirde önceki ref'ler ayrı tutulur).
3. `source.iter_extents()` için her extent:
   - `exists is False` → `extents_skipped += 1` (upload yok; sparse restore).
   - `exists is True` → `read(extent)` → `split_bytes(data, extent.offset, block_size)` → her parça için:
     - `h = chunk_hash(part)`; `offset = part.offset`; `length = len(part)`.
     - `chunk_row = session.scalar(select(Chunk).where(Chunk.chunk_hash == h))`:
       - yoksa: `store.put(h, part)`; VEYA önce store.exists(h) kontrol et — ama content-addressed: hash DB'de yoksa VERİ de store'da yok varsayılır. Tek doğruluk: DB chunks. (store.exists/hash teyidi, "diff ipucu hash doğruluk" ruhuna; DB satırı = otorite.)
       - yoksa: Chunk(chunk_hash=h, size_bytes=len(part), refcount=1) ekle; `chunks_new += 1`, `bytes_written += len(part)`.
       - varsa: `refcount += 1`; `chunks_existing += 1`.
     - `VolumeChunkMap(volume_backup_id=..., chunk_hash=h, offset_bytes=offset, length=length)` ekle.
     - manifest'e `{"hash": h, "offset": offset, "length": length}` ekle.
4. `volume_backup.tier = "t1"`; `volume_backup.object_manifest = manifest` (JSON listesi).
5. `session.commit()`. Hata durumunda `session.rollback()` then re-raise (kısmi satır kalmaz — görünür, sessiz değil).

Not: `VolumeChunkMap` satırları her export için YENİ yazılır (aynı volume_backup tek kez export edilir; re-export aynı volume_backup üzerinde yapılmaz).

- [ ] **Step 1: Failing test**

`tests/test_export.py` (mevcut store/source testlerine ekle):
```python
import pytest
from sqlalchemy import select

from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, Extent
from osbak.mover.service import ExportService, ExportStats
from osbak.models import Chunk, RestorePoint, VolumeBackup, VolumeChunkMap
from tests.fake_source import FakeVolumeSource
from tests.memory_store import MemoryChunkStore


def _restore_point(session) -> RestorePoint:
    rp = RestorePoint(kind="snapshot", instance_id=1, manifest={}, status="active")
    session.add(rp)
    session.flush()
    return rp


def _volume_backup(session, tier: str = "t0"):
    rp = _restore_point(session)
    vb = VolumeBackup(restore_point_id=rp.id, volume_ref_id=None,
                      snapshot_ref="pool-a/v-root@s-1", tier=tier, object_manifest={})
    session.add(vb)
    session.flush()
    return vb


def test_export_single_block(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    data = b"a" * 100
    src = FakeVolumeSource([Extent(offset=0, length=100, exists=True)], {0: data})
    stats = ExportService(store).export_volume(session, vb, src)
    assert isinstance(stats, ExportStats)
    assert stats.chunks_new == 1 and stats.chunks_existing == 0
    assert stats.bytes_written == 100 and stats.extents_skipped == 0
    assert vb.tier == "t1"
    c = session.scalar(select(Chunk))
    assert c is not None and c.refcount == 1
    assert store.exists(c.chunk_hash)


def test_export_dedupes_second_backup(session) -> None:
    store = MemoryChunkStore()
    data = b"b" * 100
    src = FakeVolumeSource([Extent(offset=0, length=100, exists=True)], {0: data})
    vb1 = _volume_backup(session)
    ExportService(store).export_volume(session, vb1, src)
    vb2 = _volume_backup(session)
    stats2 = ExportService(store).export_volume(session, vb2, src)
    assert stats2.chunks_new == 0 and stats2.chunks_existing == 1
    assert len(session.scalars(select(Chunk)).all()) == 1  # tek blok, refcount 2
    assert session.scalar(select(Chunk)).refcount == 2


def test_export_skips_zero_extents(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    src = FakeVolumeSource(
        [Extent(offset=0, length=50, exists=False), Extent(offset=50, length=50, exists=True)],
        {50: b"z" * 50},
    )
    stats = ExportService(store).export_volume(session, vb, src)
    assert stats.extents_skipped == 1
    assert stats.chunks_new == 1
    assert len(session.scalars(select(VolumeChunkMap)).all()) == 1
    assert session.scalar(select(VolumeChunkMap)).offset_bytes == 50


def test_export_rejects_non_t0(session) -> None:
    vb = _volume_backup(session, tier="t1")
    service = ExportService(MemoryChunkStore())
    with pytest.raises(ValueError):
        service.export_volume(session, vb, FakeVolumeSource([], {}))


def test_export_splits_large_extent(session) -> None:
    bs = DEFAULT_BLOCK_SIZE
    vb = _volume_backup(session)
    store = MemoryChunkStore()
    data = b"c" * (bs + 100)
    src = FakeVolumeSource([Extent(offset=0, length=len(data), exists=True)], {0: data})
    stats = ExportService(store).export_volume(session, vb, src)
    assert stats.chunks_new == 2
    assert len(session.scalars(select(VolumeChunkMap)).all()) == 2


def test_export_rollback_on_error(session) -> None:
    vb = _volume_backup(session)
    store = MemoryChunkStore()

    class _BadSource:
        def iter_extents(self):
            return [Extent(offset=0, length=10, exists=True)]

        def read(self, extent):
            raise RuntimeError("read failed")

    with pytest.raises(RuntimeError):
        ExportService(store).export_volume(session, vb, _BadSource())
    assert len(session.scalars(select(Chunk)).all()) == 0  # kısmi satır yok
    assert vb.tier == "t0"  # değişmedi
```

- [ ] **Step 2: Run to fail** — `pytest tests/test_export.py -v` → FAIL.

- [ ] **Step 3: Implement**

`src/osbak/mover/service.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from osbak.mover.chunker import DEFAULT_BLOCK_SIZE, Extent, chunk_hash, split_bytes
from osbak.mover.source import VolumeSource
from osbak.mover.store import ChunkStore
from osbak.models import Chunk, VolumeBackup, VolumeChunkMap


@dataclass(frozen=True)
class ExportStats:
    chunks_new: int = 0
    chunks_existing: int = 0
    bytes_written: int = 0
    extents_skipped: int = 0


class ExportService:
    def __init__(
        self,
        store: ChunkStore,
        block_size: int = DEFAULT_BLOCK_SIZE,
    ) -> None:
        self._store = store
        self._block_size = block_size

    def export_volume(
        self,
        session: Session,
        volume_backup: VolumeBackup,
        source: VolumeSource,
    ) -> ExportStats:
        if volume_backup.tier != "t0":
            raise ValueError("yalnızca T0 volume backup'ı export edilebilir")

        stats = ExportStats()
        manifest: list[dict] = []
        try:
            for extent in source.iter_extents():
                if not extent.exists:
                    stats = ExportStats(
                        stats.chunks_new, stats.chunks_existing,
                        stats.bytes_written, stats.extents_skipped + 1,
                    )
                    continue
                data = source.read(extent)
                for part in split_bytes(data, extent.offset, self._block_size):
                    h = chunk_hash(part)
                    chunk_row = session.scalar(
                        select(Chunk).where(Chunk.chunk_hash == h)
                    )
                    if chunk_row is None:
                        self._store.put(h, part)
                        session.add(Chunk(chunk_hash=h, size_bytes=len(part), refcount=1))
                        stats = ExportStats(
                            stats.chunks_new + 1, stats.chunks_existing,
                            stats.bytes_written + len(part), stats.extents_skipped,
                        )
                    else:
                        chunk_row.refcount += 1
                        stats = ExportStats(
                            stats.chunks_new, stats.chunks_existing + 1,
                            stats.bytes_written, stats.extents_skipped,
                        )
                    session.add(
                        VolumeChunkMap(
                            volume_backup_id=volume_backup.id,
                            chunk_hash=h,
                            offset_bytes=part.offset,
                            length=part.length,
                        )
                    )
                    manifest.append({"hash": h, "offset": part.offset, "length": part.length})
            volume_backup.tier = "t1"
            volume_backup.object_manifest = manifest
            session.commit()
        except Exception:
            session.rollback()
            raise
        return stats
```

- [ ] **Step 4: Run to pass** — `pytest tests/test_export.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osbak/mover/service.py tests/test_export.py
git commit -m "feat: ExportService (chunk, dedup, refcount, tier t0->t1)"
```

---

## Task 5: NOTES + tüm suite + kapanış

**Files:**
- Create: `src/osbak/mover/NOTES.md`
- (CLI/engine wiring yok — Plan 7)

**Interfaces:**
- Consumes: Task 1-4 çıktıları.

- [ ] **Step 1: NOTES yaz**

`src/osbak/mover/NOTES.md`:
```markdown
# mover — notlar (LLM'ler için)

Ne: volume verisini T1'e offload eden katman (chunk + content-addressed hash + refcount dedup).

Neden:
- `chunk_hash` = blake2b(digest_size=32).hexdigest() (64 hex — models.Chunk.chunk_hash String(64)).
- Block boyutu: 4MiB (`DEFAULT_BLOCK_SIZE`). `split_bytes` mutlak offset hizalı böler.
- Dedup: DB chunks satırı = otorite. Hash DB'de yoksa → store.put + Chunk(refcount=1);
  varsa → refcount++. Diff (VolumeSource.iter_extents) = ipucu, gerçek doğruluk hash'tir.
- `exists=False` extent'ler (zero/sparse) upload edilmez — restore sparse yazar.
- `VolumeBackup.tier` T0→T1; `object_manifest` = [{hash,offset,length}] (portability).
- Hata → session.rollback (kısmi satır kalmaz).

Tuzaklar:
- CephRbdSource ve S3ChunkStore canlı kod yollarıdır; birim test KAPSAMI DIŞI (notlive).
  Gerçek rbd diff / boto3 çağrıları canlı ortamda doğrulanır.
- re-export aynı volume_backup üzerinde yapılmaz (VolumeChunkMap tek yazım); incremental
  zincir yeni VolumeBackup satırlarıyla ilerler (engine wiring Plan 7).
- boto3 bağımlılığı opsiyoneldir; T1'siz kurulum mover store'suz çalışabilir
  (canlı kurulumda `osbak[t1]`).
```

- [ ] **Step 2: Tüm suite + commit**

```bash
pytest -v   # tümü PASS, pristine
git add src/osbak/mover/NOTES.md
git commit -m "docs: mover NOTES"
```

- [ ] **Step 3: Plan kapanışı** — bu dosyadaki tüm `- [ ]` işaretle (elle); deviasyonları (karar farkı) ADR/spec revizyonu olarak not et.

---

## Self-Review / Execution Handoff

Tasks 1-5, spec §7.1 adım 5'in (EXPORT) çekirdeğini kurar: chunker + store + source + ExportService (dedup, refcount, tier, manifest). Çıktı çalışan, test edilebilir; canlı rados/boto3 kod yolları canlı-ortam görevi (NOTES). Sonraki plan (Plan 5): restore motoru (rebuild → live swap → cold) — T1'den volume materialize + instance restore.

**Bilinen sınır (kapsam dışı):** engine/scheduler wiring (Plan 7), T2 (Plan 8), CLI export, retention/purge (Plan 7), NetApp source (Plan 6), manifest object-store kopyası (T1 store'da — restore milestone'ında bağlanır).

**Execution:** Subagent-Driven (implementer → task review → fix loop → final review → merge).


---

