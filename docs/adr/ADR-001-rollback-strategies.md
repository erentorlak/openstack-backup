# ADR-001 — Rollback/restore stratejileri ve araştırma düzeltmeleri

- Tarih: 2026-08-23
- Durum: **Kabul edildi**
- Kapsam: osbak mimarisinin restore/rollback davranışının temeli

---

## Bağlam (kaydedilen araştırma bulguları — D1..D5)

2024.1 (Caracal) birincil kaynaklarından doğrulanmıştır (kaynaklar aşağıda).
Bu düzeltmeler önceki taslak tasarımları geçersiz kılar ve repo'nun yerçekimidir:

| # | Bulgu | Mimari sonuç |
|---|---|---|
| **D1** | Nova **root-volume detach'i engelliyor** ("Cannot detach a root device volume", Caracal ve 2025.x) | `detach → revert → attach` akışı imkânsız. Asla yazılmaz. |
| **D2** | **Cinder `os-revert`** yalnızca `available` (attach'siz) volume'da, **yalnızca en son** snapshot'la, **boyut eşitliğiyle** çalışır | Birincil mekanizma olamaz (boot volume'da kullanılamaz). |
| **D3** | **RBD'de tutarlı grup snapshot'ı YOK** (yalnızca bağımsız per-volume snapshot'lar) | Instance içi tutarlılık için guest-agent quiesce + back-to-back per-volume snapshot. |
| **D4** | **NetApp Cinder snapshot'ları `.snapshot/` içinde görünmez** (geçici ONTAP CG snapshot → FlexClone → silme). **SnapDiff halka açık değil** (v3 REST yalnızca lisanslı partnerlere) | NetApp veri okuma yolu **uygulamanın kendi ONTAP snapshot'ları** üzerindendir; incremental = dosya mtime/size + hash dedup. |
| **D5** | **Skyline'da runtime 3. parti plugin API'si yok** (modüller source-level gömülür) | Standalone web app + Keystone auth; Skyline entegrasyonu sonradan (reverse-proxy/iframe veya source-level modül). |

Doğrulanmış ek kabiliyetler:
- Nova **`swap_volume`** root dahil tüm attachment'larda çalışır; koşullar:
  server **ACTIVE/PAUSED/RESIZED** (STOPPED değil), yeni volume **detached**,
  `new.size ≥ old.size`; swap sonrası **reboot**. Instance UUID + IP korunur.
- Ceph **`rbd snap rollback`** (storage-direct, in-place); RBD resizelı image'da
  başarısız olabilir → soğuk yolda pre-flight şartı.
- NetApp restore, Cinder driver'ın kanıtladığı **klon+path swap** desenine
  dayanır (ONTAP-içi, atomic).
- Cephx ile yalnızca "kendi snapshot'larına" yetki kısıtlaması **mümkün değildir**
  (capability granularity: daemon → pool → namespace → object_prefix). Ayrıcalık
  kodu tarafında, kendi `bkp-` prefix konvansiyonu ve pre-flight ile sınırlanır.
- ONTAP FlexVol başına max **1023 snapshot**, varsayılan **%5 snapshot reserve**.
- Skyline auth deseni: browser Keystone token tutmaz; backend şifre→scoped token
  alır, imzalı httpOnly cookie verir, API'leri kullanıcının token'ıyla proxyler.
  Keystone OIDC **IdP olamaz**; WebSSO (federated) mümkün.

Kaynaklar: cinder/nova 2024.1 kaynak kodu ve release notes, ceph docs
(`rbd diff`, cephx user-management), netapp KB (SnapDiff, .snapshot, snapshot
limits, FlexClone), skyline-console/apiserver docs ve FAQ, keystone docs
(application credentials, trusts, federation).

Detaylı kaynak listesi ve doğrulama notları: `docs/specs/2026-08-23-osbak-architecture.md`
"Kaynaklar ve doğrulama" bölümünde saklanır.

---

## Karar: Üç deterministik restore/rollback stratejisi

Strateji **PLAN anında** instance durumu + kullanıcı tercihi ile seçilir.
Çalışma anında sessiz alternatif yol **yoktur** (runtime fallback yok). Her
stratejinin kendi pre-flight koşulları vardır.

| Strateji | Kod adı | Instance durumu | Açıklama | Volume UUID | Instance UUID |
|---|---|---|---|---|---|
| Nova swap | `live` | ACTIVE/PAUSED/RESIZED | snapshot'tan clone → her attachment takas → reboot | değişir | **korunur** |
| Storage-direct soğuk | `cold` | STOPPED | Ceph: `rbd snap rollback`; NetApp: ONTAP klon+rename (config'te seçilebilir: ONTAP clone+rename veya `.snapshot`→aktif dosya NFS kopyası) | **korunur** | **korunur** |
| Kimliği koruyarak yeniden kur | `rebuild` | silinmiş/yok | açıkça tutulan port'larla (aynı IP/MAC) yeniden kur | değişir | değişir |

### `live` — Nova swap_volume

1. PREFLIGHT: server `ACTIVE/PAUSED/RESIZED` (STOPPED/SHELVED değil); kota;
   klonlanabilir kaynak mevcut (en ucuzu T0; T0 yoksa T1/T2'den volume
   materialize edilir — pahalı ama mümkün).
2. Her volume için snapshot'tan **clone** yarat (Ceph: RBD CoW clone; NetApp:
   FlexClone). Clone < mevcut boyut ise **extend** (swap şartı `new.size ≥ old`).
3. Her attachment için `openstack server volume update <server> <old> <new>`
   (root dahil — swap yolu root detach engeline tabi değildir).
4. `reboot`.
5. Eski volume'ları refcount/retention kuralıyla temizle.

Sıcak (downtime'sız) dönüş. İş sonrası kısa I/O kesintisi + reboot beklenir.

### `cold` — storage-direct

Koşul: instance **STOPPED** (guest yazmıyor — canlı guest altında RBD rollback
güvensiz: guest cache + QEMU writeback tutarsız görüntü üretebilir).

- Ceph: `rbd snap rollback <img>@<snap>` — attach devam eder, volume UUID aynı,
  Cinder/Nova state değişmez. PREFLIGHT: image snapshot sonrası **resize**
  edilmedi (RBD rollback başarısız olabilir).
- NetApp: iki alt-strateji config'te seçilir (ikisi de deterministik, runtime
  fallback değil):
  - `ontap-clone-rename`: snapshot'tan FlexClone → orijinal LUN/dosya yoluna
    atomik takas (Cinder driver'ın `_swap_luns` deseni). Ucuz, ONTAP-içi.
  - `nfs-filecopy`: `.snapshot/<snap>/volume-<uuid>` → aktif dosyaya NFS kopyası.
    Pahalı (tam okuma+yazma) ama tamamen bizim kontrolümüzde, ONTAP restore
    API'sine bağımlı değil.
- **Sınır bağı:** `cold` ve T0'dan klonlama `live` yalnızca T0 (native)
  snapshot **hâlâ dururken** çalışır. T0 düştükten sonra `cold` imkânsızdır;
  `live` ancak T1/T2'den volume materialize edilerek yapılır (pahalı);
  `rebuild` her zaman T1/T2'den mümkündür. UI bunu kullanıcıya duruma göre sunar.

### `rebuild` — kimliği koruyarak yeniden kur

Orijinal instance yoksa/silinmişse: açıkça tutulan port'larla (aynı IP+MAC)
yeni instance; flavor/SG/metadata/user_data/keypair aynı; manifest'ten.

---

## Gerekçe

- Nova root detach engeli (D1) ve `os-revert` kısıtları (D2) `detach→revert`
  yolunu kapsam dışı bırakır → `live` swap + `cold` storage-direct seçildi.
- `cold` en az state değişikliğini verir (volume + instance UUID korunur) ve
  "snapshota dön" senaryosunun doğal yanıtıdır; güvenliği STOPPED şartıyla
  sağlanır.
- `live` canlı dönüşün tek desteklenen yoludur; volume UUID değişimi kullanıcıya
  açıkça gösterilir.
- Strateji seçimi PLAN'da yapılır: durum değişikliği PLAN'dan APPLY'a kadar
  yeniden doğrulanır; uyuşmazlıkta apply reddedilir.

## Sonuçlar

- Numaralı kullanıcı akışı: "Snapshot → bişey yap → aynı makinede dön" =
  instance çalışıyorsa `live`, kapalıysa `cold`. UI her ikisini sunar.
- ADR'lerden bağımsız olarak provider arayüzü bu üç stratejiyi capability
  bayraklarıyla duyurur (bkz. mimari spec "Provider arayüzü").
- Uygulama sırasında doğrulanacak tek açık nokta: ONTAP REST'te single-file
  restore endpoint'in varlığı; yoksa `nfs-filecopy` veya `ontap-clone-rename`
  yeterlidir (klon+rename Cinder tarafından kanıtlanmıştır).
