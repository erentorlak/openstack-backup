# snapshot — notlar (LLM'ler için)

Ne: instance'ın storage snapshot'ını alıp restore-point olarak kataloga yazan orkestratör.

Neden:
- Preflight (keystone/instance/durum) önce; `SnapshotPreflightFailed` geçmezse yükselir.
- Volume pool yalnız `os-vol-host-attr:host` (`host@driver#pool`) → pool None durumu
  deterministik hata (atlama yok).
- Quiesce: `require_consistent` ise batch freeze; unquiesce HER ZAMAN (finally —
  zorunlu teardown, fallback değil). `allow_crash` ise quiesce yok.
- Restore-point manifest'i ManifestBuilder çıktısı; objek-store kopyası T1'de (Plan 4).
- Kismi sizinti: coklu-volume snaphot'unda sonraki patlarsa, once basarilan ref'ler
  best-effort `provider.delete(ref)` ile silinir (teardown), orijinal hata re-raise.
- `SnapshotPreflightFailed` neden tasir: katalog instance yok / pool yok / provider yok
  bos report yerine `message=` ile gercek nedeni gosterir (test: carries_cause).

Tuzaklar:
- Provider yok → `ProviderUnavailable` → `SnapshotPreflightFailed` (sessiz "boşta kal" yok).
- Gerçek rados kod yolu canlı ortamda doğrulanır; birim test yalnızca davranış sözleşmesi.
- Quiesce SDK yüzü kurulu openstacksdk'ya göre doğrulanmıştır (release-gated).
