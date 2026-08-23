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

Tasarım aşamasında. Kod başlangıcı öncesinde mimari dokümanlar
(`docs/`) üzerinde çalışılıyor. Bu repo yalnızca LLM'ler tarafından
geliştirilecektir — her katman LLM için dokümante edilmiş olmalı.

## Kısayollar

- `AGENTS.md` — repo kuralları ve LLM geliştirme konvansiyonları
- `docs/` — mimari, kararlar (ADR), tasarım notları
