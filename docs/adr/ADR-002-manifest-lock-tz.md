# ADR-002 — Manifest kilit/dışlamalar + tz tutarlılığı

- Tarih: 2026-08-23
- Durum: **Kabul edildi**
- Kapsam: Milestone 1 review follow-up'ları (manifest şema, zaman damgaları)

## Bağlam

Milestone 1 tamamlandı; final whole-branch review şu noktaları flagledi:
- Manifest'in **kilitli üst düzey anahtar seti**, spec §7.1 adım 2'deki alanların
  bir kısmını (user_data, port QoS, vnic_type, keypair dışında) içermiyor; bu
  **bilinçli kapsam küçültmesi** — ama AGENTS.md "kayıt önce" kuralı gereği
  gerekçesi ADR'de kayıtlı olmalı.
- `Job.started_at/finished_at` ve `RestoreOp.finished_at` **tz-less** `DateTime`,
  `created_at`/`last_seen_at` ise `DateTime(timezone=True)` — tutarsız.

## Kararlar

1. **Manifest dışlamaları bilinçlidir ve bu ADR ile kayıt altındadır.** Kilitli
   üst düzey anahtar seti: `schema_version, captured_at, project_id, instance,
   flavor, block_device_mapping, network, security_groups, server_groups`.
   Dışlananlar ve neden:
   - `user_data` (cloud-init): instance silindikten sonra Nova API'den genellikle
     yeniden alınamaz; gerçek değeri snapshot-anı yakala (manifest capture)
     gerektirir. Restore'da restore-point manifest'inden gelir; henüz
     yakalanmıyor. **Gelecek karar:** snapshot pipeline'ında yakala ve alanı ekle
     (o zaman ADR güncellenir). Geriye dönük eksik kabul edilir.
   - port `qos_policy_id` / `vnic_type`: Nova/Neutron envanterinden türetilebilir
     ama BDM başına düzen çıkarması restore milestone'ına ertelendi; şu an
     `network.ports`'ta `fixed_ips/security_group_ids/allowed_address_pairs`
     yakalanıyor. **Gelecek karar:** restore-edilebilirlik için gerektiğinde
     eklenir (ADR güncellenir).
   - keypair `key_name` dışı: keypair public key'in kendisi Nova'dan çekilemez;
     yalnızca adı saklanır (restore'da aynı ad var mı diye doğrulanır).
2. **tz tutarlılığı:** tüm zaman damgası kolonları `DateTime(timezone=True)`.
   `Job.started_at/finished_at`, `RestoreOp.finished_at` tz-aware yapılır.
3. **Kilit değişmez:** yeni üst düzey manifest anahtarı eklemek = ADR/spec
   güncellemesi gerektirir (ADT-001'in "kayıt önce" ruhu).

## Sonuçlar

- Manifest `domain_id` ve `config_drive` normalize (tek yol okuma).
- Geriye dönük `user_data` eksikliği restore anında kullanıcıya açıkça gösterilir.
- Gelecek alan eklemeleri bu ADR'nin revizyonuyla yapılır, sessiz değil.
