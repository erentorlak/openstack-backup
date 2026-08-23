# Çalışma disiplini protokolü

Bu depoda her oturumun uyduğu İŞLEYİŞ. AGENTS.md'nin açılımıdır; o dosya her
oturumda yüklenir, bu protokol yalnızca gerektiğinde okunur. Amaç: kontrolü
kaybetmemek. İki token — **kayıt** (state'in doc'ta yaşaması) ve **doğrula**
(iddianın kanıtla gelmesi).

---

## 1. İş döngüsü

Her görev şu sırayı geçer. Her adımın bitti sayılma koşulu yanında yazılı.

1. **kayıt** — Görevin amacı, hangi doc'a/kabule dayandığı yazılır (todo'da
   varsa açılır). *Bitti =* görev tek cümleyle ifade edilebiliyor ve ilgili
   dosyalar belli.
2. **araştır / doğrula** — Davranış birincil kaynaktan (2024.1 Caracal) kanıtla
   beslenir; gerekirse hemen subagent. *Bitti =* iddiaların her biri bir kanıta
   bağlı (`docs/` veya todo'da).
3. **plan / tasarım** — Yapılacak değişikliğin şekli seçilir; seçenekler varsa
   gerekçesiyle biri seçilir. *Bitti =* değişiklik bir doc'ta/planda yazılı.
4. **onay (kapı)** — Mimari/geri dönüşsüz işlerde tasarım onayı alınır.
   *Bitti =* kapıdan geçildi (onay var).
5. **uygula** — Kodu yaz, doc güncelle. *Bitti =* değişiklik tamam, test varsa
   yazıldı.
6. **doğrula** — Doğrulama komutu koşulur, çıktı gösterilir. *Bitti =* kanıt
   iddiayı doğruladı (veya başarısızlık rapor edildi).
7. **kapat / kaydet** — Karar ve sonuç düzenli hale getirilir, commit atılır.
   *Bitti =* değişiklik ve gerekçesi doc'ta + commit'te.

Bir adım takılırsa icat edilmez: durulur, durum rapor edilir, doğrulama için
subagent çağrılır (aşağıya bak).

---

## 2. Subagent politikası

Token sınırı yok. Doğrulama/araştırma gerektiği **anda** subagent çağrılır;
iki+ bağımsız konu varsa **aynı mesajda paralel** dispatch edilir.

**Ne zaman:** (a) release-gated bir davranışın doğrulanması, (b) bilinmeyen bir
API/sürümün araştırılması, (c) çoklu bağımsız görev, (d) uzun okuma/inceleme
görevleri (e) yeni bir konu alanına sıfır bağlamla giriş.

**Prompt kontratı** (her dispatch'te): rol, hedef, birincil kaynaklar, net
output kontratı ("şunları döndür"), research ise "kod yazma" açıkça belirtilir.
Subagent **self-contained** olmalı — ortak bağlam tekrarlanır; asla
"yukarıdaki konuya bak" denmez.

**Teyit:** subagent çıktısına körü körüne güvenilmez, ama her iddia yeniden
araştırılmaz — kritik/riskli iddialar spot-check edilir.

---

## 3. Doğrulama protokolü

- **release-gated:** OpenStack davranışı sürümden sürüme değişir → kanıt mutlaka
  **2024.1 (Caracal)** dalından/notlarından. Koddaki güncel master, 2024.1'den
  sapabilir; ikisini ayrı tut.
- **kanıt tipleri:** doğrulama komutu çıktısı · dosya satırı (satır numaralı)
  · birincil doc URL'si.
- **kanıtla-bitti:** "çalışıyor / bitti / doğru" iddiasından önce ilgili komut
  koşulur. İddia ve çıktı aynı mesajda gösterilir.
- **doğrulama yoksa:** yokluğu açıkça söylenir ("X doğrulanamadı"), iddia
  yumuşatılır.

---

## 4. Git disiplini

- Doğrulanmış kilometre taşı başına **küçük commit**; commit mesajı
  `tür(kapsam): özet` biçiminde, depo da yoksa bu biçimi kurar.
- **Secret asla** (config örnekleri `.sample` olarak gider).
- Karar doc'ları (ADR) değişiklikle birlikte commit'lenir; gerekçesiz değişiklik
  commit'lenmez.
- push / PR / tag yalnızca kullanıcı isterse yapılır.

---

## 5. Kapılar (geri dönüşsüzler)

- **Tasarım onayı yoksa kod yok** — mimari/kapalı işlerde onay kapısı atlanmaz.
- **Geri dönüşsüz işlem yok** — plan → preflight → apply ayrımı; her apply
  adımı kendi ön-koşulunu yeniden doğrular.
- **Kayıt yoksa ilerleme yok** — karar doc'ta olmadan o kararın peşinden gidilmez.

---

## 6. Oturum ömrü

- Uzayan işte el değiştirme: kritik bağlam `docs/`'a yazılır; el değişince
  AGENTS.md + ilgili doc'lar okunur — örtük belleğe güvenilmez.
- Bu protokol değişirse AGENTS.md'deki özet ile bu dosya birlikte güncellenir
  (tek doğruluk kaynağı kuralı).
