# osbak — Mimari Spec

- Tarih: 2026-08-23
- Durum: **Taslak (onay bekliyor)**
- Karar kayıtları: `docs/adr/ADR-001-rollback-strategies.md`

Bu belge, osbak uygulamasının tek doğruluk kaynağıdır. Önceki sohbet ve
araştırma bulguları buraya damıtılmıştır; diğer dokümanlar buraya işaret eder.

---

## 1. Amaç ve kapsam

Ceph (RBD) ve NetApp (ONTAP) üzerinde oluşturulmuş OpenStack instance'ları için
**agentless** backup, restore ve snapshot yönetimi sağlayan, açık kaynak, web
arayüzlü bir uygulama.

- OpenStack'in kendi backup mekanizmalarını kullanmaz (cinder-backup, Nova
  image snapshot'dan yararlanmaz).
- Guest'e backup ajanı kurulmaz; veri, storage katmanından okunur/yazılır.
  (İsteğe bağlı tam tutarlılık için imagelarda QEMU guest-agent bulunabilir.)
- Restore'un anlamı: **"instance istediğim özelliklerle tekrar ayağa kalksın"**
  — yalnızca volume geri getirmek değil; kimlik/ağ/güvenlik metadata'sı da.

## 2. Hedef ortam ve varsayımlar

| Varsayım | Değer |
|---|---|
| OpenStack sürümü | **2024.1 (Caracal)** |
| Storage | Ceph (Cinder RBD), NetApp ONTAP (Cinder NFS driver ağırlıklı; iSCSI/FC desteklenebilir) |
| Ortam | Boot-from-volume instance'lar (root + data volume'lar) |
| Dağıtım | OpenStack dışında tek VM (vCenter'da); OpenStack API'sine, Ceph public net'e, ONTAP data LIF'lerine ve S3'e doğrudan erişim |
| Ölçek | 100–1000 instance, 10–100 TB, saatlik + günlük + aylık planlar |
| Mimarlık niyeti | NetApp'sız kurulum çalışır (modüler/open source) |

## 3. Kavramlar

- **Snapshot** (`tür=snapshot`): anlık görüntü; T0'da (native storage) yaşar;
  amaç **aynı makinede o noktaya dönmek** (kısa retention).
- **Backup** (`tür=backup`): snapshot + T1/T2'ye offload; amaç **uzun vadeli**
  koruma ve tam restore.
- **Restore point**: kullanıcının gördüğü birim; bir instance'ın
  manifest + volume verisi. hem snapshot hem backup için ortak.
- **Tier**:
  - **T0** — native snapshot (RBD snapshot / ONTAP snapshot), hızlı dönüş.
  - **T1** — bölge içi S3-compatible (RGW/MinIO): content-addressed chunk deposu
    (S3 anahtarı `chunk/<hash>`), refcount dedup (T1 bir kere yüklenir, tüm
    restore point'ler paylaşır).
  - **T2** — uzak S3 (Object Lock compliance): aylık başına **self-contained,
    append-only pack** dosyaları (restic paket deseni) — volume verisi +
    manifest; T1 gibi cross-month dedup yok (basitlik + immutability önceliği).
- **Manifest**: instance'ın tam metadata grafiği (JSONB, şemasız).

## 4. Araştırma bulguları ve tasarım sınırları

Ayrıntı `docs/adr/ADR-001-rollback-strategies.md` bölüm "Bağlam"da. Özet (Caracal,
doğrulanmış):

1. Nova **root-volume detach engelli** → `detach→revert→attach` imkânsız.
2. Cinder `os-revert`: yalnızca available volume + en son snapshot + boyut eşitliği.
3. RBD'de tutarlı grup snapshot'ı yok → per-volume snapshot + guest quiesce.
4. NetApp Cinder snapshot'ları `.snapshot`'ta görünmez; **SnapDiff halka açık değil**.
5. Skyline'da runtime 3. parti plugin API'si yok → standalone + Keystone auth.
6. Nova `swap_volume` root dahil her volume'da çalışır (server ACTIVE/PAUSED/
   RESIZED iken; `new.size ≥ old` şartı; swap sonrası reboot; STOPPED/SHELVED değil).
7. Cephx ile "yalnızca kendi snapshot'ları" yetkisi tanımlanamaz → kod tarafı sınırlama.
8. Skyline auth deseni: backend-held token + imzalı httpOnly cookie; Keystone OIDC IdP olamaz.

## 5. Sistem bileşenleri ve dağıtım

Tek VM'de (modüler kod; ileride worker'a taşınabilir):

```
tek VM (vCenter, OpenStack dışı)
├── osbak-api        FastAPI      — Keystone auth, RBAC, REST API
├── osbak-console    Vue SPA      — web arayüzü (Skyline uyumlu stack)
├── osbak-scheduler  APScheduler  — saatlik/günlük/aylık planlar
├── osbak-engine     job runner   — state machine, işçi iş parçacıkları
├── osbak-preflight  dry-run      — plan/validate/apply
├── osbak-catalog    PostgreSQL   — restore_points, manifest, jobs, policies
└── providers/       plugin'lar   — ceph (opsiyonel ekstra), netapp (opsiyonel ekstra), s3target
```
- Storage provider'lar opsiyonel extra'lardır: `pip install osbak[ceph]` ve/veya
  `osbak[netapp]`; en az **biri** kurulu olmalıdır. NetApp'sız kurulum netapp
  kodunu import etmez; Ceph'sız kurulum da simetrik olarak çalışır.

- Dağıtım: Docker Compose (veya systemd + venv); merkezi `config.yaml`.
- Ölçek notu: engine tek işlemde thread-pool ile paralel çalışır; kod worker
  soyutlamasıyla ayrılabilir (katalog = Postgres, iyi ise ayrı VM'lere taşınır).

## 6. Katalog veri modeli (PostgreSQL)

```sql
projects(id, keystone_project_id, enabled)
-- (opsiyonel: kullanıcı bazlı scope için user_map)

instances(id, instance_uuid UNIQUE, project_id, last_seen_at)
volume_refs(id, instance_id FK, volume_uuid, boot_index, size_gb,
            volume_type, backend, pool,
            format  -- nfs: raw|qcow2 (yalnızca NFS data-path keşfi erişirse)
           )

restore_points(id, kind SNAPSHOT|BACKUP, instance_id FK,
               created_at, policy_id, status,
               manifest JSONB  -- şemasız tam instance tanımı
              )
volume_backups(id, restore_point_id FK, volume_ref_id FK,
               snapshot_ref,   -- rbd: pool/img@snap · ontap: flexvol/snap
               tier T0|T1|T2,
               object_manifest JSONB,  -- chunk hash listesi + refcount ipucu
               incremental_from_id NULL
              )
chunks(hash BLOB PKEY, size_bytes, refcount)      -- T1 content-addressed deposu
volume_chunk_map(volume_backup_id FK, chunk_hash FK,
                 offset_bytes, length)             -- volume → chunk sıralaması
-- T2 ek katalog tablosu gerektirmez: pack listesi object store manifest'indedir.

jobs(id, kind, policy_id, state, dry_run, started_at, finished_at, error)
policies(id, name, kind, schedule(s), retention JSONB, quiesce_policy,
         selection JSONB)  -- tag/instance seçimi
restore_ops(id, restore_point_id, strategy LIVE|COLD|REBUILD, state,
            mapping JSONB,  -- eski→yeni UUID
            created_by, created_at, finished_at, error
           )
```

- `manifest` **şemasız JSONB**: Nova/Neutron API sürümler arası alan ekler;
  katı şema her upgrade'de kırılır. Restore'da bilinmeyen alanlar yok sayılır,
  saklanan her şey kullanıcıya gösterilir.
- Manifest'in bir kopyası her restore point için — türü SNAPSHOT (T0-only) da
  olsa — register anında T1/T2 object store'a yazılır (bkz. 7.1 adım 6):
  katalog kaybı ≠ backup kaybı garantisi snapshot'lar için de geçerlidir.

## 7. Veri akışları

### 7.1 Ortak pipeline

```
DISCOVER → MANIFEST → QUIESCE → SNAPSHOT ─┬─► register (tür=SNAPSHOT, T0)
                                           └─► EXPORT → T1 → (aylık) → T2
                                                   → register (tür=BACKUP)
```

1. **DISCOVER**: Nova/Cinder/Neutron'dan envanter tazele; `vol.host`
   (`os-vol-host-attr:host`, `host@driver#pool`) → backend/pool eşle.
   **Doğrulandı (2024.1):** `provider_location` ve `os-vol-host-attr:backend`
   public API'de YOK (admin dahil) — pool yalnızca host string'inden türetilir.
   Çapraz-proje listeleme tek admin token + `all_projects=True (+project_id=)`
   ile (Nova/Cinder `all_tenants`; `project_id` filtresi yalnız
   `all_tenants=True` iken çalışır). NetApp format tespiti (`raw|qcow2`) keşifte
   yalnızca NFS data-path etkinse yapılır; aksi halde `format` bilinmiyor.
2. **MANIFEST**: tam instance tanımı topla (flavor+extra_specs, BDM+volume_type,
   port'lar (MAC, fixed_ip, SG, QoS, vnic_type), SG kuralları (tam), server
   group, keypair, user_data, config_drive, AZ, metadata, tags, floating IP).
   UUID referanslarını DEĞİL nesnelerin kopyasını sakla (silinmiş olabilir).
3. **QUIESCE**: politika `require_consistent` ise guest-agent freeze (paralel,
   timeout'lu); başarısızsa **job abort** (asla sessiz crash'e düşme).
   `allow_crash` ise quiesce denenmez.
4. **SNAPSHOT**: her instance'ın volume'ları için per-volume snapshot.
   - Ceph: back-to-back RBD snapshot (bizim cephx'imizle, `bkp-instance-<ts>-<n>`).
   - NetApp: **kendi ONTAP snapshot'ımız** (REST) — FlexVol seviyesi; o
     FlexVol'daki tüm hedef instance'ların guest'leri aynı batch'te freeze edilir.
   - Farklı backend'leri karıştıran instance: guest bütün olarak bir kez freeze
     edilir; sonra her volume kendi backend'inde snapshot'lanır (bkz. §12).
   - Instance içi tutarlılık RBD'de atomik DEĞİL (D3) → quiesce sağlar.
5. **EXPORT** — sadece BACKUP türünde:
   - Ceph incremental: `rbd diff --whole-object --from-snap <önceki>` (fast-diff
     + object-map şart) → yalnız değişen extent'ler → chunk+hash → T1.
   - NetApp incremental: kendi iki snapshot'ımız arasında `volume-<uuid>`
     dosyasının mtime/size'ı (`.snapshot/<snap>` üzerinden); değişmediyse
     **metadata-only version** (refcount), değiştiyse tam okuma + chunk hash
     dedup → T1.
   - Diff = **ipucu**, hash = **doğruluk** (benji deseni).
6. **INDEX/VERIFY**: restore edilebilirlik doğrulaması (örnek chunk okuma,
   manifest tutarlılığı), katalog güncelle. **register** (tür ne olursa olsun):
   manifest kopyası object store'a yazılır. Retention'a göre temizlik ayrı
   scheduled job (bkz. §13).

### 7.2 NetApp NFS okuma yolu (detay)

- ONTAP snapshot REST:
  `POST /api/storage/volumes/{flexvol_uuid}/snapshots {"name":"bk-<ts>"}`.
- Backup VM, SVM data LIF'ini **NFSv3** ile mount eder (snapdir erişimi için;
  export policy: backup VM subnet + `snapdir` seçeneği; gerekirse
  `vserver nfs -v3-hide-snapshot disabled`).
- Okuma: `<export>/.snapshot/bk-<ts>/volume-<uuid>`; format raw (varsayılan,
  qcow2 ise qemu-img/qemu-nbd üzerinden).
- İleride iSCSI/FC: FlexClone volume + LUN map (provider'da ayrı data reader).

## 8. Restore ve rollback — stratejiler

ADR-001'den: üç deterministik strateji, PLAN anında seçilir.

| Strateji | Kod | Durum | Sonuç |
|---|---|---|---|
| Nova swap | `live` | ACTIVE/PAUSED/RESIZED | swap'ta volume UUID değişir, instance UUID korunur |
| Storage-direct soğuk | `cold` | STOPPED | volume + instance UUID korunur; T0 snapshot'ı gerekir |
| Kimliği koruyarak yeniden kur | `rebuild` | silinmiş/yok | yeni UUID'ler; aynı IP/MAC (açıkça tutulan port'larla) |

Strateji koşulları (PLAN'da seçilir, runtime fallback yok):
- `live` — klonlanabilir bir kaynak gerekir. En ucuzu T0 native snapshot'tan
  CoW clone; T0 yoksa T1/T2 chunk'larından volume **materialize** edilip
  (yeniden oluşturulup) swap yapılır — çalışır ama tam okuma + yazma maliyeti.
- `cold` — **yalnızca** T0 native snapshot dururken (storage-direct, in-place);
  T0 düşünce `cold` imkânsızdır.
- `rebuild` — T1/T2'den her zaman mümkündür.
- NetApp `cold` alt-stratejisi config anahtarı:
  `providers: netapp: rollback_mode: clone_rename | nfs_filecopy` (ikisi de
  deterministik; bkz. ADR-001).

Kullanıcı akışı (UI):
- **"Snapshota dön"** (aynı makine): instance çalışıyorsa `live` (reboot'luk),
  durdurulmuşsa `cold` (downtime'da, UUID korunur).
- **"Restore"** (instance kayboldu vb.): `rebuild` — R1 (aynı kimlik, istenen
  IP/MAC) veya R2 (yeni instance / test / DR, IP çakışmasında kullanıcıya sor).
- Depolama seçenekleri UI'da: flavor (spec bozuksa gizli `restore-<hash>`
  yarat), volume type, network/port (aynı IP veya yeni), MAC koruma, SG'ler
  (yoksa 2 geçişte kur), keypair, user_data, AZ, isim, metadata.

`swp`/`live` adımları:
1. clone (Ceph: RBD CoW clone; NetApp: FlexClone); boyut < mevcut ise extend.
2. Her attachment için `server volume update <srv> <old> <new>` (root dahil).
3. `reboot`. 4. eski volume'ları retention'a göre temizle.

`rebuild` bağımlılık sırası (her adım "var mı / yarat / çakışıyor mu + eski→yeni
UUID eşlemesi katalogda): **SG(önce boş grup sonra kurallar) → volume'lar →
port'lar (istenen IP/MAC) → flavor → server group → instance → floating IP**.

## 9. Provider arayüzü (plugin, open source)

`osbak.providers` — tek dokümante arayüz; capability bayraklarıyla Ceph/NetApp
ayrışır. Storage provider'lar **opsiyonel extra**'dır: `pip install osbak[ceph]`
ve `osbak[netapp]`; en az biri gerekli. NetApp'sız kurulum netapp kodunu
import etmez.

```python
class Provider(Protocol):
    name: str
    capabilities: ProviderCapabilities
    #    can_snapshot: bool
    #    native_diff: bool            # Ceph True, NetApp False
    #    data_path: "rbd"|"nfs"|"iscsi"|"fc"
    #    rollback: frozenset({"live","cold","rebuild"})
    #    source_kind: "pool"|"flexvol"|"share"

    def snapshot(self, target: VolTarget, name_prefix: str) -> SnapshotRef
    def diff(self, base: SnapshotRef|None, target: VolTarget,
             read_chunk_cb: Callable) -> Iterable[Extent]
    def mount_read_path(self, snapref: SnapshotRef) -> ReadPath
    def rollback_cold(self, target: VolTarget, snapref: SnapshotRef, mode: str) -> None
    # clone-from-snapshot, delete_snapshot, preflight_checks...
```

- Provider'ı yalnızca config'te aktifse yükle; `importlib` ile isteğe bağlı.
- Diff ipucudur; gerçek doğruluk content-addressed chunk + hash kataloğu.

## 10. Auth ve Web UI (Keystone, Skyline uyumlu)

Skyline'in kanıtlanmış deseni:

- Browser Keystone token'ı **tutmaz**. `POST /auth/login` → backend Keystone'e
  `password → scoped token` → imzalı httpOnly session cookie (JWT) verir.
- Tüm OpenStack çağrıları backend'den kullanıcının token'ıyla proxylenir
  (keystoneauth1 Session).
- **Proje değiştirici**: kullanıcının projeleri; switch = unscoped → re-scope.
- **RBAC**: backend'de rol kontrolü (reader/member/admin; implied roles);
  UI yalnızca backend'in sunduklarını gösterir. Hiçbir işlem UI'da
  gizlemeye güvenmez — API katmanında doğrulanır.
- **WebSSO** (opsiyonel config): Keystone federated OIDC (mod_auth_openidc +
  `trusted_dashboard` + `sso_callback_template`) — Skyline ile aynı.
- **Skyline entegrasyonu** (ileride): standalone; reverse-proxy ile aynı
  origin'e alınabilir veya source-level modül; iframe için frame-allow şart.
- Altyapı hesabı (uzun süreli engine işleri): app credentials (proje başına)
  veya trust — kullanıcı şifresi saklanmaz.

## 11. Pre-flight / dry-run motoru

API'de `plan` ve `apply` ayrı çağrı. `plan` (dry-run) doğrulama ağacı döner:

- **erişim**: keystone/ceph/ontap/s3 kimlik doğrulama, keystone servis kullanıcısı rolü
- **kapasite**: FlexVol snapshot reserve %, aggregate, RBD pool %, object store, kota
- **durum**: instance/volume status, port/IP/Floating uygunluğu, flavor/SG/keypair varlığı
- **yetkinlik**: RBD incremental için pool'da `fast-diff` + `object-map` image
  özellikleri; seçilen stratejinin gerektirdiği cephx/ONTAP/S3 cap'leri
- **limit**: FlexVol ≤1023 snapshot, snapshot sonrası resize (RBD rollback) engeli
- **çakışma**: istenen IP/MAC'in boşta olması

Her kontrol PASS/FAIL + resource delta tablosu. `apply` her adımın ön-koşulunu
yeniden doğrular; tek başarısızlıkta job FAIL + kaydedilmiş state ile rollback.
**Sessiz alternatif yol yoktur.**

## 12. Tutarlılık politikası

- Politika başına `require_consistent | allow_crash`; config/UI'dan seçilir,
  çalışma anında değişmez.
- `require_consistent`: QEMU guest agent freeze (imajda `hw_qemu_guest_agent=yes`
  + `os_require_quiesce=yes`). Zaman aşımı → abort.
- NetApp FlexVol batch: aynı FlexVol'daki hedef instance'ların guest'leri
  birlikte freeze edilir (çünkü tek ONTAP snapshot tüm FlexVol'ü kaplar).
  ONTAP snapshot'ı, hedef olmayan volume'ları da kaplar; biz yalnızca hedef
  dosyaları okuduğumuz ve hedef guest'ler freeze edildiği için bu zararsızdır.
- Farklı backend'leri karıştıran instance: guest bir kez freeze edilir; sonra
  her volume kendi backend'inde snapshot'lanır — Ceph volume'ları RBD, NetApp
  volume'ları ilgili (FlexVol, run) ONTAP snapshot'ına düşer. Per-volume
  seçim `volume_refs.backend`'ten yapılır.

## 13. Retention ve katmanlar (varsayılan, config-driven)

`policies.retention` JSONB'sinde yaşar; UI'dan değiştirilebilir. Plan tanımı
hangi katmanları üreteceğini de söyler (`offload` hedefi):

```
hourly:   T0                    { keep: 24 }   # native snapshot
daily:    T0 + T1               { keep: 14 }   # bölge içi obje deposu
monthly:  T0 + T2               { keep: 12 }   # S3 Object Lock compliance
```

- Her plan çalıştığında **T0 snapshot üretir** (aynı makinede "snapshota dön"
  her zaman son birkaç nokta için çalışır); `offload` hedefine (T1/T2) göre
  export yapılır.
- Purge: refcount/label ile güvenli temizlik; snapshot hâlâ bir restore point'e
  referans veriyorsa silinmez.
- **Sınır bağı:** `cold` rollback yalnızca T0 native snapshot dururken
  çalışır. T0 düşünce: `live` ancak T1/T2'den volume materialize edilerek
  yapılır (pahalı), `rebuild` her zaman mümkündür (bkz. §8 koşullar).

## 14. Güvenlik ve yetki matrisi

- Keystone: servis hesabı + kullanıcı bazlı proje scope; RBAC implied roles.
- Ceph: ayrı `client.osbak`:
  `mon 'profile rbd' osd 'profile rbd pool=volumes, profile rbd pool=osbak' mgr 'profile rbd pool=volumes, profile rbd pool=osbak'`
  - **Doğrulama notu:** `mgr 'profile rbd'` ifadesinin geçerliliği kurulum
    sırasında cephx user-management dokümanından teyit edilecek (mgr cap
    tanımı dağıtıma göre değişebilir); `mon`/`osd` satırları temeldir.
  - yalnızca kendi `bkp-` prefix'li snapshot'lar; Cinder/Glance snapshot'larına
    dokunma (kod + pre-flight); Cinder'ın keyring'i asla.
- ONTAP: snapshot create/delete + veri okuma haklı, silme hakları sınırlı
  kullanıcı; kendi `bk-` prefix'li snapshot'lar.
- S3: ayrı kullanıcı, minimum scope; Object Lock retention'ı uzun vadeli politikayla.
- Manifest'te tenant verisi olabilir → RBAC üstünde erişim denetimi.

## 15. State machine & job model

Backup job:
```
DISCOVER → MANIFEST → QUIESCE → SNAPSHOT → [EXPORT] → INDEX → DONE
   (herhangi bir noktada FAIL — kayıtlı state ile)
```
Restore op:
```
PLANNED → PREFLIGHT_PASS → EXECUTING → VERIFY → DONE
                         ↘ FAILED (− rollback kaydı)
```
- İdempotency: her adım bir `job_step` kaydı; job dedupe key (instance, kind,
  ts penceresi) — çift snapshot yaratılmaz.
- Plan→apply arası durum değişirse apply reddedilir, yeniden plan.

## 16. API yüzeyi (özet; gerçek yol yapım sırasında netleşir)

```
POST /auth/login | /auth/switch-project
GET  /projects; /instances; /restore-points; /policies
POST/PUT/DELETE  /policies         # plan (schedule, quiesce, retention, selection) + retain düzenleme
POST /snapshots          {instance, name}            → restore point (T0)
POST /backups/plan       {policy}                    → plan (dry-run)
POST /backups/apply      {plan_id}
POST /restores/plan      {point_id, strategy, options} → plan (dry-run)
POST /restores/apply     {plan_id}
POST /rollbacks/plan     {point_id, strategy: live|cold}
POST /rollbacks/apply    {plan_id}
GET  /jobs; /restore-ops; /health
```
UI = bu API'nin tüketicisidir; API tek kaynaktır.

## 17. Hata durumu ve kurtarma

- Manifest/object manifest kopyaları object store'da → katalog kaybında yeniden
  canlandırma (kök: `GET /restore-points` → katalogdakiler + S3'teki).
- İdempotent adımlar: tekrar çalıştırma güvenli.
- Job FAIL: hata mesajı + tamamlanan adımların state'i kalıcı; kurtarma elle
  (`retry` plan) veya temizlik job'ı.

## 18. Teknoloji yığını

- Backend: Python 3 / FastAPI; openstacksdk, keystoneauth1, boto3,
  (netapp) `netapp-ontap`, (ceph) `rados`+`rbd` bindings (birincil), `rbd` CLI
  doğrulama yedeği.
- Katalog: PostgreSQL. Zamanlama: APScheduler (Celery'ye gerek yok; worker
  soyutlaması kod tarafında).
- Frontend: Vue 3 SPA (Skyline konsol uyumu).
- Dağıtım: Docker Compose; config.yaml (tüm bağlantı + politika varsayılanları).

## 19. LLM dokümantasyon planı

- `AGENTS.md` — sabit kurallar (yüklü). `docs/discipline.md` — protokol.
- Bu spec — davranışın tek kaynağı.
- `docs/adr/` — karar gerekçeleri.
- Modül başına NOTES: ne + neden + tuzak; özellikle providers, preflight,
  state machine, manifest, katalog.

## 20. Yapım sırası (teslimat)

1. Katalog şeması + discovery + manifest capture (restore'un %80'i)
2. Pre-flight motoru (plan/validate/apply)
3. Snapshot orkestrasyonu (Ceph provider) + quiesce
4. Data mover (chunk+hash) + T1 (S3-compatible)
5. Restore motoru: `rebuild` (R2 sonra R1) → `live` swap → `cold`
6. NetApp provider (ONTAP snapshot + NFS `nfs-filecopy` okuma + `clone-rename`)
7. Scheduler + retention (config-driven)
8. T2 (S3) + Object Lock
9. Web UI + Keystone auth + RBAC + Skyline uyumluluğu

Her adım: plan → doğrula (2024.1 kaynak) → uygula → test → ADR/katalog güncelle.

## 21. Açık kararlar (spek üzerinde netleştirilecek)

- Repo adı (çalışma: **osbak**), GitHub org/remote.
- UI detay seti: restore sihirbazındaki tüm değiştirilebilir alanlar (flavor,
  network, SG...) kesin liste.
- Retention varsayılanları kesinleşecek; config-driven olduğundan kilit değil.
- ONTAP tek-adım restore endpoint varlığı (implementation'da doğrulla).
- İdempotency penceresi ve concurrency seviyesi (ölçek testiyle).

## 22. Kaynaklar ve doğrulama

Tasarım sınırları 2024.1 (Caracal) ve ilgili satıcı dokümanlarından doğrulanmıştır.
Birincil kaynaklar (yeni bir iddia yazmadan önce buradan doğrula):

- Cinder 2024.1: `cinder/api/v3/volumes.py` (revert), `cinder/volume/api.py` (available gate),
  `cinder/volume/manager.py` (revert + temp snapshot + generic fallback), `cinder/group/api.py`
  — microversion 3.40 (`VOLUME_REVERT`); driver'lar: `rbd.py` (snap rollback),
  `netapp/dataontap/block_cmode.py`, `nfs_cmode.py` (revert-as-clone-path-swap, CG snapshot)
- Nova 2024.1: `nova/api/openstack/compute/volumes.py` (root detach bloğu),
  `nova/compute/api.py` (attach/detach/swap koşulları: ACTIVE/PAUSED/RESIZED)
- Nova spec: detach-boot-volume (onaylı, uygulanmadı)
- Ceph: https://docs.ceph.com/en/latest/man/8/rbd/ (diff/export-diff, snap, clone),
  https://docs.ceph.com/en/latest/dev/rbd-diff/ , user-management (cephx,
  `profile rbd`, namespace), fast-diff/object-map
- NetApp KB: SnapDiff sürümleri ve lisans kısıtı; `.snapshot` NFS erişimi
  (snapdir, `-v3-hide-snapshot`); FlexVol başına 1023 snapshot; %5 snapshot reserve;
  FlexClone REST; snapshot REST `POST /api/storage/volumes/{uuid}/snapshots`
- Skyline: skyline-apiserver (login, session JWT, policy FAQ), skyline-console
  (build-time module/menu — runtime plugin yok)
- Keystone: application credentials, trusts, federation/WebSSO (trusted_dashboard,
  sso_callback_template); Keystone OIDC IdP değildir
- Desen referansı: benji (plugins: I/O / storage / transform; diff-as-hint;
  content-addressed; scrub) — https://benji-backup.me ; restic design.rst

Bu listeye yeni bir doğrulama eklendiğinde ADR veya bu bölüm güncellenir.

---

Bu spec, `docs/discipline.md` döngüsüne göre implementasyonun temelidir.
Değişiklik = yeni ADR veya spec revizyonu.
