# ROADMAP / Yapılacaklar (Todo)

- Tarih: 2026-08-24
- Durum: kanlı doküman — her milestone öncesi güncellenir
- Kaynak: `docs/specs/2026-08-23-osbak-architecture.md` (§20 yapım sırası, §21 açık
  kararlar), `docs/adr/ADR-002-manifest-lock-tz.md`, modül `NOTES.md`'leri, yapılan
  kod review'larının ertelenen bulguları.
- Kural: bir maddeyi "bitti" işaretlemek için önce `kanıtla-bitti` (test/suite çıktısı
  veya canlı doğrulama). Yeni bir karar → `docs/adr/`'ye kayıt, serbest "kapatmalar"
  yok.

Not: şu ana dek **Milestone 1–6** tamamlandı (katalog→manifest, preflight, snapshot,
data mover, restore rebuild + CLI). Bu listedeki kalemler onların üstüne kurulur.

---

## A. Kısa vade — kod-yalnız (canlı altyapı gerektirmez)

- [ ] **A1. Plan-time preflight kararı** (review bulgusu): `RestoreService.plan` şu an
  DB-only, doğrulama yalnız apply'de. Karar: plan'da opsiyonel `gateway` ile erken
  `original_instance_absent` kontrolü + plan-zamanı durum anlık görüntüsü mü tutulsun
  (yoksa §15 "durum değişti → apply reddi" nasıl güçlendirilsin). Önce ADR.
- [ ] **A2. Executor FAILED idempotency/rollback tasarımı** (review): orta-plan hatasında
  gateway'de yaratılan SG/volume/port ref'leri kalıcı; re-apply duplication riski.
  Karar: teardown mı, adım-idempotency mi, `retry` mı — önce tasarım + ADR.
- [ ] **A3. `only=` / preflight ağacı dışı**: `Job` ORM kolonu var (`quiesce_policy`),
  scheduler yok — Job makinesi/backup makinesi (§15 DISCOVER→…→INDEX) kurgusu.
- [ ] **A4. RestoreOp VERIFY durumu** (§15): `…→EXECUTING→VERIFY→DONE`; VERIFY ne
  doğrular (boot? port-up? volume-attach?) — tanımla + state machine'e ekle.
- [ ] **A5. RBD snapshot adı doğrulama** (canlı-yol `ceph.py`): `snap_name()` çıktısı
  (`:`,`+` karakterleri RBD adlandırması için geçersiz) + `_utc_iso()` tek çağrı
  (ad ile `created_at` aynı an). Birim test başlangıcı (saf fonksiyonlar).
- [ ] **A6. PostgreSQL + migration** (spec §18: katalog PostgreSQL): alembic baseline,
  CIsız da `init_db` çalışan komut. Şu an engine generic (`create_engine(url)`).
- [ ] **A7. CI**: GitHub Actions; `pytest` + coverage (var olan 127 test). push'ta koşar.
- [ ] **A8. Manifest kopyası object store'a** (spec §6): restore-point register'ında
  manifest + object_manifest kopyasını T1 store'a yaz — katalog-kaybı garantisi için.
  Tasarım: aynı `ChunkStore` arayüzü yeter mi, ayrı manifest anahtarı mı?

## B. Orta vade — canlı altyapı gerektirir (provider milestone'ı)

- [ ] **B1. Ceph provider canlı** (§20-3): `snapshot`/`delete` gerçek rados; `fast-diff`/
  `object-map` ile diff okuma (data mover `CephRbdSource.iter_extents`); cephx
  `profile rbd` + `mgr cap` gereksinimleri canlı dokümandan teyit (§22).
- [ ] **B2. S3ChunkStore canlı doğrulama** (boto3): 404 sözleşmesi belgelenen davranış
  (fix uygulandı) canlıda onaylanır; T1 offload gerçek senaryo + restore okuma.
- [ ] **B3. NetApp ONTAP provider** (§20-6): snapshot create/delete REST
  (`POST /api/storage/volumes/{uuid}/snapshots`), NFS `nfs-filecopy` okuma,
  `clone-rename`, FlexClone; FlexVol başına 1023 snapshot + %5 reserve sınırları
  (spec §22). Modül + `capabilities` + CLI factory wiring (providers/NOTES).
- [ ] **B4. Restore data yolu** (spec §8): executor `source_snapshot=None` → volumeler
  boş; chunk → volume maddileştirme (T1 store'dan) bağlanır — restore'un "veri geri
  gelme" vaadi. ADR gerekir.
- [ ] **B5. `live` (swap_volume)** stratejisi (§8): canlı instance'a `swap_volume` ile
  dönüş; CLI `--strategy` genişletilir (şu an yalnız `rebuild`).
- [ ] **B6. `cold` (storage-direct)** stratejisi (§8): STOPPED instance'da in-place
  RBD `snap rollback` / ONTAP restore. Bağımlılık: A (ACTIVE kısıtı kararı).
- [ ] **B7. T2 + Object Lock** (§20-8): uzun dönem immutable depo; manifest/T1→T2
  taşıma, object lock konfigürasyonu.
- [ ] **B8. Scheduler + retention** (§20-7): APScheduler ile plan-tetikleme
  (`Policy` ORM hazır), retention temizlik job'ı, config-driven varsayılanlar.

## C. Uzun vade — web/arayüz/olgunlaştırma

- [ ] **C1. Web UI** (§20-9): FastAPI REST (`GET/POST /restore-points`, `/policies`,
  `/restore-plans` — spec §16) + Keystone auth + RBAC + imzalı httpOnly cookie
  (backend-held token; spec §10).
- [ ] **C2. Vue 3 SPA** konsol (Skyline uyumlu stack): restore sihirbazı, snapshot/plan
  listesi, durum ekranları.
- [ ] **C3. Skyline entegrasyonu** (ileride): standalone + reverse-proxy; runtime 3.
  parti plugin API'si olmadığından build-time console uyumu (§10).
- [ ] **C4. Tam manifest capture** (ADR-002 gelecek kararları): `user_data`'yı snapshot
  pipeline'ında yakala ve alana ekle (ADR revizyonuyla); port QoS/vnic_type
  restore-edilebilirlik için ekleme; keypair `key_name` doğrulaması restore'da.
- [ ] **C5. Preflight ağacı genişletme** (§11): capacity, permission/competence,
  limit (FlexVol≤1023, RBD-resize), conflict (IP/MAC free) check'leri; `resource_delta`
  doldurma.
- [ ] **C6. Provider opsiyonelliği** (AGENTS): `osbak[netapp]`/`osbak[t1]`/`osbak[ceph]`
  extra'larının import-boundary testi (netapp'suz kurulum netapp import etmesin).

## D. Düşünülmesi gereken / açık kararlar

- [ ] **D1. ACTIVE kısıtı** (review bulgusu): `SnapshotOptions.goal_state="ACTIVE"`
  STOPPED instance'ın soğuk snapshot'ını engelliyor. Kaldır → `goal_state=None` + soğuk
  yolda quiesce atlanır mı, yoksa kısıt bilinçli mi? Karar gerekli.
- [ ] **D2. IDempotency penceresi + concurrency** (§21): ölçek testiyle netleşecek;
  aynı policy aynı anda kaç kez tetiklenebilir, yeniden-çalıştırma hangi pencerede güvenli.
- [ ] **D3. ONTAP tek-adım restore endpoint'i** (§21): implementation'da varlığı/şekli
  doğrulanacak (REST tek çağrı restore varsa kullan).
- [ ] **D4. UI restore sihirbazı alan seti** (§21): kullanıcının restore'da
  değiştirebileceği alanların kesin listesi (flavor, network, SG, AZ, IP...) spec'e
  işlenecek.
- [ ] **D5. Retention varsayılanları** (§21): config-driven olduğundan kilit değil ama
  başlangıç değerleri netleştirilecek (saatlik/günlük/aylık T0/T1/T2 tutma süreleri).
- [ ] **D6. Plan→apply state-change reddi nasıl keskinleşir** (review/§15): şu an apply
  preflight'ı yeniden koşuyor; plan-zamanı anlık görüntü (mapping/state hash'i)
  saklanmalı mı — A1 ile birlikte karar.
- [ ] **D7. Repo adı/ürün adı** (§21): çalışma adı **osbak**, GitHub repo şu an
  `openstack-backup`; ürün adı ve CLI gelecekte yeniden adlandırılırsa ADR + README
  güncellenir (kullanıcı kararı).
- [ ] **D8. S3 manifest store tek mi ayrı mı** (A8 ile birlikte): chunk store ile
  manifest store aynı bucket/anahtar ailesi mi, yoksa ayrı depo mu — güvenlik/retention
  farkı.

## E. Doğrulamalar / dış bağımlılıklar (release-gated)

- [ ] cephx: `profile rbd` + namespace + `mgr` cap'leri 2024.1/user-management'dan teyit
  (spec §22; snapshot/restore sırasında gerekli mi, hangi scope).
- [ ] Nova BDM public API'de `boot_index`'in expose durumu (discovery/NOTES) — eksiksiz
  BDM bilgisi için.
- [ ] `nfs-filecopy` ve `.snapshot` NFS erişiminin (`snapdir`, `-v3-hide-snapshot`)
  kuruluma göre durumu (ONTAP provider öncesi).
- [ ] Skyline policy FAQ / login JWT akışı (web UI milestone öncesi).

---

Her milestone şu sırayla: **plan → doğrula (2024.1 kaynak) → uygula → test → ADR/NOTES
güncelle**. Sıra önerisi: A bloğu (kod-yalnız) bir sonraki effort, ardından canlı
altyapı erişimi açıldığında B bloğu.
