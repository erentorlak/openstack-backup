# AGENTS.md

Bu repo **yalnızca LLM'ler tarafından geliştirilir**. İnsan kod yazmaz.
Her karar ve tuzak, başka bir ajanın sıfır bağlamla çalışabilmesi için dokümante
edilir. Tüm dokümanlar bu amaçla yazılır: ne + neden + hangi tuzak.

## Çalışma kuralı

- OpenStack davranışı **release-gated**: sürümden sürüme değişir. Bir davranışa
  güvenmeden önce onu **2024.1 (Caracal)** birincil kaynağından doğrula
  (docs.openstack.org, ilgili release notes, koddaki 2024.1 dalı). Belleğin
  taze değil.
- Gerçek altyapıya asla bağlanma; bağlanacak hiçbir adım (backup/restore/snapshot)
  geliştirme sırasında çalıştırılmaz. Credential'lar yalnızca config'ten okunur,
  asla hardcode edilmez.
- Bir değişiklik = test + doğrulama komutuyla birlikte gönderilir. Doğrulama
  komutu yoksa o gerçek açıkça söylenir.

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
  çalışır (`pip install osbak[netapp]` gibi).

## Konvansiyon

- Yığın: Python 3 / FastAPI (backend), Vue (frontend). Single-VM dağıtım.
- Provider'lar `providers/<name>` altında, tek dokümante arayüz + capability
  bayrakları (can_native_diff, data_path, ...). Diff = ipucu, hash = doğruluk.
- Karar gerekçeleri `docs/adr/` altında yaşar (neden swap_volume, neden kendi
  ONTAP snapshot'ları, cephx kapsamı, state machine). Yeni bir karar → yeni ADR.
- Katalog `restore_points` + `manifest (JSONB)` ayrımı; manifest şemasız tutulur
  (Nova/Neutron API zamanla alan ekler).

## Nereden başla

- `README.md` — proje özeti ve durum
- `docs/` — mimari, ADR'ler, LLM notları (dolduruluyor)
