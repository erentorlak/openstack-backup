# manifest — notlar (LLM'ler için)

Ne: instance'ın tam tanımını şemasız dict olarak üreten katman.

Neden:
- Manifest restore'un %80'i: flavor (tam spec), BDM, network/port (IP/MAC/SG),
  security group kuralları (kopya), server group üyelikleri.
- Şemasız dict (JSONB): Nova/Neutron API sürümler arası alan ekler; katı şema
  her upgrade'de kırılır.

Tuzaklar:
- Anahtar seti milestone sonunda kilitlendi. Alan eklemek = spek/ADR değişikliği.
- Restor'da bilinmeyen anahtar yok sayılır, saklanan her şey kullanıcıya gösterilir.
- `captured_at` UTC ISO; JSONB'a yazarken her şey JSON-serializable olmalı.
