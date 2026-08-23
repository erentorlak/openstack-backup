# osbak — agentless OpenStack backup, restore & snapshot

Modular, open-source backup **ve** snapshot yönetimi uygulaması. OpenStack'in
kendi backup mekanizmalarını kullanmaz; veriyi doğrudan storage katmanından
okur/yazar (agentless). Web arayüzü OpenStack Keystone ile kimlik doğrular,
Skyline'a sonradan bağlanabilir.

## Hedef ortam

- OpenStack **2024.1 (Caracal)**
- Storage backend'ler: **Ceph (RBD)** ve **NetApp ONTAP** (NFS ağırlıklı)
- Uygulama, OpenStack dışında (vCenter VM) tek makinada çalışır
- 100–1000 instance, 10–100 TB, saatlik + günlük + aylık(S3) planlar

## Durum

Milestone 1–6 tamamlandı ve main'e merge edildi. Çalışır durumda:

- **Katalog/discovery:** `osbak inventory-refresh` (proje/sunucu/volume UPSERT)
- **Manifest:** `osbak manifest-show <instance-uuid>`
- **Snapshot:** `osbak snapshot-take <instance-uuid> [--consistent]` (quiesce +
  per-volume snapshot → restore point; kısmi hatalarda ref temizliği + rollback)
- **Restore:** `osbak restore plan <restore-point-id> [--strategy rebuild]` ve
  `osbak restore apply <restore-op-id>` (iki fazlı: PLANNED → … → DONE|FAILED,
  kimlik/ağ/security metadata'sıyla yeniden inşa)

Hâlâ **bekleyen** katmanlar (provider milestone'ında, canlı altyapı ile doğrulanır):
- Canlı storage yolları: Ceph RBD snapshot/delete, ONTAP, S3 object store (T1)
- Restore veri yolu (chunk → volume maddileştirme; `os-backup restore` şu an
  volumeleri boş yaratır)
- Yönetim web arayüzü (FastAPI + Keystone auth) ve planlı S3/T2 zinciri

Bu repo yalnızca LLM'ler tarafından geliştirilecektir — her katman LLM için
dokümante edilmiş olmalı.

## Kısayollar

- `AGENTS.md` — repo kuralları ve LLM geliştirme konvansiyonları
- `docs/specs/2026-08-23-osbak-architecture.md` — mimari spec (tek doğruluk kaynağı)
- `docs/adr/` — karar kayıtları (ADR-001: rollback stratejileri, ADR-002: manifest kilit/tz)
- `docs/discipline.md` — çalışma disiplini protokolü
- `docs/plans/` — milestone uygulama planları (tamamlananlar tarihsel kayıttır)
- `src/osbak/*/NOTES.md` — her modülün LLM notları (tuzaklar, davranış sözleşmeleri)

## Başlarken

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
osbak --config config.yaml inventory-refresh
osbak --config config.yaml manifest-show <instance-uuid>
osbak --config config.yaml snapshot-take <instance-uuid> --consistent
osbak --config config.yaml restore plan <restore-point-id>
osbak --config config.yaml restore apply <restore-op-id>
```
