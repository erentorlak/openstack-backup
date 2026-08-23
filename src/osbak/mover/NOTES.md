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
- Aynı export içinde aynı chunk tekrar gelirse: new Chunk add'inden sonra `session.flush()`
  şart — sessionmaker autoflush=False, scalar() bekleyen INSERT'i görmez; flush yoksa
  duplicate satır → UNIQUE ihlali (fix: review bulgusu + test).
- boto3 bağımlılığı opsiyoneldir; T1'siz kurulum mover store'suz çalışabilir
  (canlı kurulumda `osbak[t1]`).
