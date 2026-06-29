# Birim Maliyet + Fiyatlandırma Modeli

> Amaç: "Bir kullanıcı bana aylık kaça mal olur, kaça satarım, karlı mıyım?"
> sorusuna **koddan çıkarılmış** bir model. Rakamlar tahmin değil, senin kendi
> kodundaki fiyat + çağrı deseninden türetildi. Yine de **kesin sayı için
> tahmin etme — ölç** (aşağıda nasıl olduğu var).

## Maliyet kalemleri

| Kalem | Kaynak | Ölçek | Not |
|---|---|---|---|
| **LLM (Gemini)** | Sohbet + haber zenginleştirme | Kullanımla artar | **Ana marjinal maliyet** |
| Veri API'leri | yfinance, TEFAS, NewsAPI, F&G | Çoğu ücretsiz/limit | NewsAPI ölçekte ücretli olur |
| Hosting | Cloud Run (min-instances=0) | Boştayken ~₺0 | Trafikle ölçeklenir |
| Veritabanı | SQLite → Neon Postgres | Düşük | Ölçekte Neon ücreti |

## LLM maliyeti — koddan türetilmiş

Senin config'in (`backend/app/agents/llm.py:15`):
- Model: **gemini-3.1-flash-lite** · **girdi $0.25 / 1M tok** · **çıktı $1.50 / 1M tok**

Tur başına çağrı deseni (`supervisor.py` — paralel map-reduce):
- strategist (1 plan çağrısı) + paralel uzmanlar (ort. 2–3 ajan × ~2 çağrı) +
  advisor (koşullu) + synthesizer (1) ≈ **tur başına ~8 LLM çağrısı** (hafif 3 –
  ağır 14 aralığı).

Çağrı başı tahmin (orta): ~2.500 girdi + ~600 çıktı tok
→ maliyet = (2500×0.25 + 600×1.50) / 1.000.000 = **~$0.0015 / çağrı**

| Senaryo | Çağrı/tur | $/tur | ₺/tur* |
|---|---|---|---|
| Hafif soru | ~3 | ~$0.005 | ~₺0.17 |
| Tipik soru | ~8 | ~$0.012 | ~₺0.40 |
| Ağır araştırma | ~14 | ~$0.021 | ~₺0.70 |

\* 1 USD ≈ ₺33 varsayımı (güncel kuru kendin gir).

### Aylık maliyet / aktif ödeyen kullanıcı

| Kullanım | Tur/ay | LLM maliyeti ($/ay) | ₺/ay* |
|---|---|---|---|
| Az aktif | 40 | ~$0.5 | ~₺16 |
| Tipik | 100 | ~$1.2 | ~₺40 |
| Ağır | 300 | ~$3.6 | ~₺120 |

Haber zenginleştirme **paylaşılan** maliyettir (kullanıcı başına değil): tüm
kullanıcılar aynı `news_article` tablosunu okur. Günlük birkaç yüz başlık ×
batched enrichment ≈ günde ~$0.05–0.30 → kullanıcı sayısına bölününce ihmal
edilebilir.

## Tahmin etme — ÖLÇ (zaten loglu)

`llm.py`'deki `TokenLogger` her çağrıdan sonra **gerçek** girdi/çıktı/maliyet
logluyor (`token_usage | ... | cost=$...`). Kesin birim maliyet için:

1. 20–30 gerçek sohbet yap (farklı sorular).
2. Logları `cost=` üzerinden topla, sohbet sayısına böl → **gerçek $/tur**.
3. Bu modeldeki tahminleri o sayıyla değiştir.

## Fiyatlandırma — freemium (KARAR: ₺199/ay, 15 mesaj ücretsiz)

| Katman | Ne içerir | Fiyat |
|---|---|---|
| **Ücretsiz** | Takip + dashboard + **ayda 15 koç mesajı** + manuel haber | ₺0 |
| **Pro** | Sınırsız* koç + proaktif uyarılar + haftalık özet | **₺199/ay** (KDV dahil) |

\* "Sınırsız" = adil kullanım (ör. 200 tur/ay) — marjı korumak için **rate-limit
şart** (kod: `free_monthly_chat_turns`, Pro uncapped). 1000 tur/ay power-user
maliyeti ₺500'e çıkar → fair-use cap önerilir.

> Uygulandı (kod): `pro_plan_price=199`, `pro_plan_currency=TRY`,
> `free_monthly_chat_turns=15` (`backend/app/settings.py`).

## Başa-baş — eski model 3 kalemi atlamıştı

Eski tablo sadece LLM maliyetini sayıyordu. **Gerçek başa-baş** için 3 kalem şart:

1. **KDV %20** — ₺199 etiket → net gelir ₺199 ÷ 1,20 = **₺166**.
2. **iyzico komisyonu ~%3** — ₺166 × 0,97 ≈ **₺161 net/ay**.
3. **Ücretsiz-kullanıcı yükü** — her ödeyen, dönüşüm oranına göre N bedava
   kullanıcı taşır. 15-tur tavanla free maliyeti ≈ **₺3/ay** (ort. ~6 tur kullanım).

**Varsayımlar:** 1 USD ≈ ₺42 (güncel kuru gir) → tipik tur ~₺0,50; Pro tipik
120 tur ≈ ₺60 LLM + ₺10 altyapı = **₺70 doğrudan maliyet**.

Net marj/ödeyen = (net gelir − ₺70 doğrudan) − (free yükü):

| Dönüşüm | ₺149 (eski) | **₺199 (yeni)** |
|---|---|---|
| %3 | −₺46 ❌ | −₺5 ❌ |
| %5 | −₺7 ❌ | **+₺34 ✅** |
| %8 | +₺16 | +₺57 |
| %10 | +₺23 | +₺64 |

**Sonuç:** ₺149 ~%7-8 dönüşüm istiyordu (riskli); **₺199 ~%5 dönüşümden pozitif**.
En büyük kaldıraç **ücretsiz tavan**: 50→15'e indirince free yükü ~3 kat azaldı.

**Sıradaki kaldıraçlar:**
- **Yıllık plan** (~₺1.990/yıl ≈ 2 ay bedava): nakit + retention + iyzico
  komisyonunu yılda 1'e indirir.
- **FX:** maliyet USD, gelir TL — çeyrekte bir fiyat gözden geçir.
- Gerçek $/tur'u `TokenLogger`'dan ölç, bu tahminleri değiştir.

## Kritik uyarılar

- **FX riski:** maliyet USD, gelir TRY. TL değer kaybederse marj erir — fiyatı
  TL'de sabit tutarsan riski sen taşırsın. Periyodik fiyat gözden geçirmesi planla.
- **Adil kullanım/rate-limit olmadan** birkaç power-user marjı yer. v1'de tur
  sayacı + aylık cap ekle.
- Gemini fiyatları ve `news_api`/Neon ücretli katmanları değişir — bu modeli
  çeyrekte bir güncelle.
- Bu model **marjinal** maliyet içindir; senin zamanın, sabit hosting tabanı,
  pazarlama (CAC) ayrı. Başabaş = (sabit giderler) / (kullanıcı başı brüt marj).
