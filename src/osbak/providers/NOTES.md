# providers — notlar (LLM'ler için)

Ne: storage backend soyutlayıcısı; `SnapshotProvider` Protocol, şu an `CephProvider`.

Neden:
- Capability modeli provider'ın neleri desteklediğini tek noktada söyler; diff/rollback
  gibi heterojen davranışlar capability bayraklarıyla ayrışır.
- `ProviderUnavailable` deterministik — provider yoksa preflight FAIL'e çevrilir.

Tuzaklar:
- `CephProvider` rados bağlamasını `find_spec` ile yoklar; venv'de rados yoksa kurulamaz
  (beklenen davranış — canlı ortamda `osbak[ceph]`).
- Gerçek rados komutları canlı doğrulamada; birim test snap_name/capabilities/probe.
- Yeni provider = yeni modül + capabilities + CLI factory wiring.
