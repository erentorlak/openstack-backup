# restore — notlar (LLM'ler için)

Ne: restore motorunun planlama + rebuild çekirdeği. Manifest (JSONB) → saf RestorePlan →
RestoreGateway mutasyonları ile kimliği koruyarak yeniden kurulum (aynı IP/MAC, yeni UUID).

Neden:
- RestorePlanner: SAF (I/O yok) — manifest → adım kümesi; var/yok kararları ensure_*
  idempotentliğine ve preflight'a bırakılır. Strategy LIVE/COLD → RestorePlanError("henüz desteklenmiyor").
  SG 2-geçiş (önce bütün kabuklar, sonra kurallar — kurallar başka grubun id'sine atıf yapar).
- RebuildExecutor: seq sıralı yürütme; RestoreOp state machine EXECUTING→DONE|FAILED;
  mapping eski→yeni id tutar (`volumes`/`ports`/`security_groups`/`flavor`/`server`), FAILED'da
  kısmi mapping korunur. Teardown+re-raise except (AGENTS izinli kalıp); sonradan teardown yok.
- RestoreGateway = mutation-only ayrı Protocol; read tarafı (OpenstackGateway) DEĞİŞMEZ.
- mapping şeması katalog JSONB'de (RestoreOp.mapping).

Tuzaklar:
- SDKRestoreGateway (canlı mutasyon) KASITLI boş — gerçek Nova/Neutron/Cinder çağrıları
  canlı ortamda doğrulanır (provider milestone). Birim testler FakeRestoreGateway ile döner.
- Port fixed_ip yalnızca keep_ip=True iken eklenir; aksi halde Neutron atar.
- find_or_create_flavor: exact spec eşleşmesi; "en yakın flavor" YOK (extra_specs kaybeder).
- restore_ops mapping anahtarları: volume/port'lar için ORİJİNAL id (key'in ":" sonrası),
  security_groups için ad (idempotent ensure ad ile çalışır).
