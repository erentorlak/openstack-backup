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
- Remote grup referansı: 2-geçiş — kural `remote_group_id` (eski id) planner'da `.remote_group_name`'e çevrilir, executor yeni id'ye çözer; bilinmeyen id → RestorePlanError (sessiz skip YOK).
- AZ asimetrisi (bilinçli, provider milestone'a): create_volume yalnız options.availability_zone kullanır; create_server instance.availability_zone'a düşer — real manifest'te volume farklı AZ'a düşebilir.
- Sessiz SG skip portta: manifest security_group listesinde olmayan port SG'si düşer (builder wanted_sg_ids invariant'ı sayesinde bugün ulaşılamaz); provider milestone'da plan-time RestorePlanError önerilir.
- boot_index: builder data volumeleri -1 (root 0) verir → ascending sort volume_keys'i -1 önce getirir; gerçek Nova BDM sıralaması provider milestone'da doğrulanacak.
- Restore edilen volumeler BOŞ: executor source_snapshot=None geçer; chunk-veri maddileştirme (T1 store) henüz bağlı DEĞİL — canlı restore veri yoludur, provider milestone'da gelir.
- server_groups ve floating IP: spec §8 rebuild sırasında yer alır ama bu planın step kontratı DIŞI (bilinçli); manifest server_groups alanı şu an adımsız düşer.
- JSON kalıcılığı: INSERT'te op.mapping'e `copy.deepcopy(mapping)` yazılır — `dict(mapping)` SİĞ kopya (iç dict'ler paylaşılır) olduğundan FAILED yarım mapping'i (yalnız iç değişim) SQLAlchemy'nin JSON değer-eşitliği karşılaştırmasında "değişmedi" sayılıp UPDATE'ten düşerdi; DONE genelde dış anahtar eklemesi (flavor/server) yüzünden fark edilmezdi. Bitişte `op.mapping = dict(mapping)` yeterli.
