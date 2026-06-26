# FinanceCoach — SaaS Ürünleştirme Yol Haritası

> Karar: FinanceCoach'u gelir getiren bir SaaS'a çevirmek. Bu doküman bunu
> **runway'i batırmadan** (sözleşme 31 Tem'de bitiyor, ~60k TL nakit, 1-3 ayda
> gelir lazım) yapmanın gerçekçi, sıralı yolu. Kural: **önce ucuz doğrulama,
> sonra ağır inşa.** Ağır inşaya doğrulama sinyali olmadan başlamak klasik
> solo-SaaS tuzağı — ve senin kendi bildiğin "büyük şeye dal, geliri unut"
> örüntün.

## Mevcut gerçeklik (kod tabanından)

| Konu | Durum | SaaS için anlamı |
|---|---|---|
| Çok-kiracılık | `user_id=1` hardcoded; Firebase Auth erişimi geçer ama **veri izolasyonu yok** | **#1 teknik blok.** Gerçek SaaS = her sorgu kullanıcıya scope'lanmalı |
| Deploy | Cloud Run + Neon Postgres + Firebase zaten kurulu | Altyapı çoğu hazır — avantaj |
| Birim maliyet | ~$0.012/tur (bkz. `BIRIM_MALIYET_FIYAT.md`) | Marj iyi **ama** rate-limit şart |
| Ödeme | Yok | Phase 1 bloğu (iyzico/Stripe/Lemon Squeezy) |
| Regülasyon | AI zaten AL/SAT/HOLD vermiyor (bu oturumda sertleştirildi) | **Doğru SPK duruşu** — "eğitim/takip, tavsiye değil" |
| Retention kancası | Proaktif haber uyarıları **zaten var** | Para veren özellik hazır |
| Güven kanıtı | CI **eval harness** (grounding/safety skorlu) | Çoğu rakipte yok — pazarlama kozu |
| Wedge | Türk bireysel yatırımcı: TEFAS+BIST+kripto (bkz. `URUN_ODAK.md`) | Tek odak; İsviçre-çakısı değil |

## Phase 0 — DOĞRULA (≈1 hafta, ucuz, gelir işine PARALEL)

Amaç: kod yazmadan "ödeyen var mı?" sorusunu ölç. Bu, multi-tenancy'e haftalar
gömmeden önceki kapı.

1. **Landing + gerçek fiyat + bekleme listesi.** Tek mesaj (URUN_ODAK wedge'i),
   "Pro ~₺149/ay" fiyatı, "Erken erişim" e-posta formu. Toplanan e-posta =
   ödeme niyeti sinyali. (SEO/design dokümanların zaten bu yüzeyi düşünüyor.)
2. **Canlı demo** (tek-kullanıcı, seed'li) — kimse kurulum yapmadan 30sn'de
   denesin. Bu hem doğrulama hem de Phase B2B/Toptal vitrinin.
3. **10-15 müşteri görüşmesi** (`MUSTERI_KESFI.md` script'i) — gerçek acıyı +
   ödeme istekliliğini doğrula.

**KAPI:** anlamlı kayıt/ödeme sinyali yoksa → Phase 1'e geçme, wedge'i veya
kitleyi değiştir. Sinyal varsa → inşa.

## Phase 1 — ÇOK-KİRACILI MVP (asıl iş; yalnızca Phase 0 sinyaliyle)

1. **Multi-tenancy (en büyük blok).** `user_id=1` hardcode'unu kaldır; Firebase
   uid → user satırı; HER sorgu authenticated user'a scope'lansın; veri
   izolasyonu + testleri. Mevcut tek-kullanıcı veri akışları tek tek gözden
   geçirilmeli.
2. **Ödeme + abonelik.** TR için iyzico (yerel kart/3D), global için Lemon
   Squeezy/Stripe. Freemium: ücretsiz takip + 10 mesaj/ay · Pro sınırsız* +
   uyarılar.
3. **Kullanım limiti + rate-limit.** Marjı korur (power-user ayda 1000 tur
   maliyeti uçurur). Tur sayacı + aylık cap.
4. **Yeni-kullanıcı onboarding.** Boş durum → değer anına en kısa yol (tek hedef
   + risk + 1-2 sembol). Şu anki onboarding 7 alan istiyor — kısalt.
5. **Regülasyon + yasal.** Her yerde "bilgilendirme/eğitim amaçlı, yatırım
   tavsiyesi değildir"; KVKK aydınlatma + ToS/Gizlilik. (AI tarafı zaten güvenli.)

## Phase 2 — LANCH + RETENTION

- Freemium katmanları canlı; **proaktif uyarılar** retention motoru olarak öne.
- Bekleme listesine soft launch → kullan/ölç/iterate (eval harness kalite
  bekçisi olarak CI'da kalır).
- Fiyat/marj çeyrekte bir gözden geçir (FX riski: maliyet USD, gelir TRY).

## Dürüst uyarılar (tekrar)

- **Runway:** Phase 0 ucuz ve gelir işine paralel; Phase 1 yalnızca sinyal
  varsa. SaaS Ağustos kirasını ödemez — 60k köprü + B2B/Toptal hattı gelir
  motorudur, SaaS uzun bahis.
- **SPK:** B2C finansta tavsiye sınırı; konumlandırma eğitim/takip/içgörü.
- **Churn:** retail finans araçlarında bırakma yüksek; uyarı kancası tam da
  bunun için.

## İlk somut adım (öneri)

Phase 0'ın **landing + fiyat + bekleme listesi**'yle başla — hızlı, gerçek SaaS
yüzeyi, ve multi-tenancy'e haftalar gömmeden talebi ölçer. Paralelde sen müşteri
görüşmelerini yap. Sinyal gelirse Phase 1 multi-tenancy refactor'ına geçeriz.
