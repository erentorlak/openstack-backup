# discovery — notlar (LLM'ler için)

Ne: OpenStack envanterini (proje/sunucu/volume) kataloga yazan katman.

Neden:
- `gateway.py` bir Protocol soyutlamasıdır; gerçek ağ tek yüz `SDKGateway`.
- `os-vol-host-attr:host` = `host@driver#pool`; pool yalnızca buradan türetilir.
  `provider_location` public API'de YOK (2024.1 doğrulandı) — oradan asla okuma.
- Çapraz-proje listeleme: `all_projects=True` + `project_id=` (Nova/Cinder
  `project_id` filtresi yalnız `all_tenants` açıkken çalışır).

Tuzaklar:
- Mapping fonksiyonları openstacksdk `to_dict()` anahtar adlarını tek yoldan
  okur; çok-anahtar fallback YOK. Sürüm yükseltmelerinde `to_dict()` anahtar
  adları değişirse, koda fallback ekleme — testi/doğrulamayı güncelle.
- `get_flavor` bulamazsa `None` döner; manifest `"flavor": null` yazar.
- Boot disk `boot_index=0`, diğer volume'lar `-1` (Nova BDM public API'de
  exposelandığında iyileştirilecek; bu milestone'da deterministik sözleşme buydu).
