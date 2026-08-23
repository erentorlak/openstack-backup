# preflight — notlar (LLM'ler için)

Ne: her işlem öncesi çalışan doğrulama ağacı (plan → validate → apply).

Neden:
- `ValidationEngine.validate(plan_kind, ctx, only=...)` → `ValidationReport`; PASS/FAIL
  + mesaj + data. `only` apply öncesi kısmi yeniden-doğrulama içindir.
- Check kaydı `register_check` ile; (PlanKind, name) çakışması ValueError (sessiz
  üzerine yazma yok).
- Erişim probe'u yalnızca `openstack.exceptions.SDKException` yakalar (dar); diğer
  istisnalar yukarı fırlar — engine istisna yutmaz.

Tuzaklar:
- `instance_present` `ctx.data["server"]`'ı yazar, `instance_state` okur — registry
  sırasına bağlı. Server yoksa ikisi de hangi sırada olursa FAIL.
- Kapasite/yetkinlik/limit incelemeleri provider milestone'larında gelir
  (CheckKind hazır); resource_delta restore/snapshot milestone'ında dolar.
- Fallback kuralı: çok-anahtar okuma yok; "instance yok" FAIL'dır, istisna değil.
- `only` bilinmeyen adlarla sıfır sonuç üretirse `ValueError` (vacuously-green footgun
  engellendi, engine'de — test: only_with_unknown_name_raises). Kısmi uygunluk (bazı adlar
  bu plan_kind'e uygulanmaz) yine uygulananları koşar; sonuç boşsa asla rapor dönmez.
- Ortak tarama: `ctx.find_server(uuid)` (project_id, server) veya None döner; hem
  `instance_present` hem `original_instance_absent` buradan okur (tekrar eden döngü yok).
- `only=["instance_state"]` yalnız başına `ctx.data["server"]`'ı okur — taze ctx'te spurious
  FAIL üretir. Apply aynı plan-zamanı ctx'ini yeniden kullanmalı (veya durum check'i kendini
  fetch etmeli).
