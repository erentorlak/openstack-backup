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
- `only` boş/uygunsuz sonuç üretebilir: `validate(BACKUP, only=["snapshot_only"])` → 0 sonuç ama
  `passed=True` (vacuously green). Apply öncesi yeniden-doğrulama bunu kullanmadan önce
  semantik kararlaştırılmalı (bilinmeyen ad → hata, veya boş rapor → pass değil).
- `only=["instance_state"]` yalnız başına `ctx.data["server"]`'ı okur — taze ctx'te spurious
  FAIL üretir. Apply aynı plan-zamanı ctx'ini yeniden kullanmalı (veya durum check'i kendini
  fetch etmeli).
