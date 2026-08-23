# AGENTS.md

Bu repo **yalnızca LLM'ler tarafından geliştirilir**. İnsan kod yazmaz.
Her karar ve tuzak, başka bir ajanın sıfır bağlamla çalışabilmesi için dokümante
edilir. Tüm dokümanlar bu amaçla yazılır: ne + neden + hangi tuzak.

## Çalışma disiplini (kontrol döngüsü)

Kontrol kaybetmemek için her iş bu döngüden geçer; döngünün iki token'ı
**kayıt** ve **doğrula**:

1. **kayıt önce** — chat bellek geçicidir; tek doğruluk kaynağı doc'tur. Bir
   karar/bulgu kalıcı yere yazılmadan işe devam edilmez (`docs/adr/`,
   `docs/specs/`, `docs/*.md`, todo list).
2. **doğrula sonra iddia** — OpenStack davranışı **release-gated**: iddia, onu
   2024.1 (Caracal) primary kaynaktan kanıtlamadan söylenmez. Kanıt = komut
   çıktısı, dosya satırı veya kaynak URL. Tahmin iddia değildir; bellek taze
   değildir.
3. **araştır-önce-kod** — davranış doğrulanmadan kod denenmez.
4. **kanıtla-bitti** — "bitti" denmeden önce doğrulama komutu koşulur, çıktısı
   gösterilir; doğrulama yoksa o gerçek açıkça söylenir.
5. **tek iş** — her an en fazla bir `in_progress`; todo list güncel tutulur.
6. **geri dönüşsüz adım yok** — yıkıcı/güç alınmaz işlem önce planlanır,
   preflight edilir, gerektiğinde onaya sunulur. `plan → validate → apply`
   ayrımı ürünle aynı.
7. **takılınca dur** — emin olunamayan yerde icat edilmez; durulur, durum rapor
   edilir, ilgili subagent ile doğrulanır.

**Subagent politikası** — token sınırı yok; doğrulama veya araştırma gerektiği
anda **hemen** bir (veya bağımsızsa paralel birkaç) subagent dispatch edilir.
Her subagent self-contained olmalı: soru + kaynaklar + net output kontratı.
Protokolün tamamı: `docs/discipline.md`.

**Kuruluş güvenliği** — gerçek altyapıya (OpenStack/Ceph/ONTAP/S3) bağlanan hiçbir
adım geliştirme sırasında çalıştırılmaz. Credential'lar yalnızca config'ten
okunur, hardcode edilmez.

## Tasarım sınırları (release-gated doğrulandı — ihlal edilemez)

Bunlar repo'nun yerçekimi; kod bunların üzerine kurulur:

- **Root-volume detach engelli** (Nova, Caracal+). Aynı instance'a dönüşün iki
  deterministik yolu: canlı instance → `swap_volume`; kapalı instance →
  storage-direct rollback (RBD `snap rollback` / ONTAP restore). `detach →
  revert → attach` akışı imkânsız, asla yazma.
- Cinder `os-revert`: yalnızca **available** volume'da, **yalnızca en son**
  snapshot'la, **boyut eşitliği**yle çalışır.
- RBD'de tutarlı grup snapshot'ı yok → per-volume snapshot + guest-agent
  quiesce.
- NetApp Cinder snapshot'ları `.snapshot/` içinde **görünmez** (geçici ONTAP CG
  snapshot → FlexClone → silme). NetApp okuma yolu **uygulamanın kendi** ONTAP
  snapshot'ları üzerindendir. SnapDiff halka açık değil (lisanslı partnerler).
- Skyline'da runtime üçüncü-parti plugin API'si yok → standalone web app +
  Keystone auth (backend-held token); Skyline entegrasyonu sonradan.
- Provider'lar opsiyoneldir: NetApp'sız kurulum netapp kodu import etmeden
  çalışır (`pip install osbak[netapp]` gibi). En az bir storage provider gerekli.

Aşağıdaki şartlar da tasarım sınırıdır (spec'te gerekçeleri var):

- Restore'un anlamı **instance'ın kimlik/ağ/güvenlik metadata'sıyla ayağa
  kalkması**dır — yalnızca volume geri getirme değil. Manifest bu yüzden saklanır.
- Manifest kopyası her restore point için (SNAPSHOT/T0-only dahil) yazılır:
  katalog kaybı ≠ backup kaybı.
- Zamanlama ve retention config/UI'dan değiştirilir; uzun dönem (T2) S3 Object
  Lock ile immutable'dır.
- `plan → validate → apply` ayrımı hem API'de hem kodda ihlal edilmez; sessiz
  alternatif yol yoktur.

## Konvansiyon

- Yığın: Python 3 / FastAPI (backend), Vue (frontend). Single-VM dağıtım.
- Provider'lar `providers/<name>` altında, tek dokümante arayüz + capability
  bayrakları (can_native_diff, data_path, ...). Diff = ipucu, hash = doğruluk.
- Karar gerekçeleri `docs/adr/` altında yaşar (neden swap_volume, neden kendi
  ONTAP snapshot'ları, cephx kapsamı, state machine). Yeni bir karar → yeni ADR.
- Katalog `restore_points` + `manifest (JSONB)` ayrımı; manifest şemasız tutulur
  (Nova/Neutron API zamanla alan ekler).

## Nereden başla

- `docs/specs/2026-08-23-osbak-architecture.md` — davranışın tek doğruluk kaynağı (spec)
- `docs/adr/ADR-001-rollback-strategies.md` — restore/rollback kararı
- `docs/discipline.md` — çalışma disiplini protokolü (döngü, subagent, doğrulama, git)
- `README.md` — proje özeti ve durum
- `docs/` — diğer ADR'ler ve LLM notları
