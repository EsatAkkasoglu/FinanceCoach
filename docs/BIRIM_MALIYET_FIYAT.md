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

## Fiyatlandırma — freemium

| Katman | Ne içerir | Fiyat |
|---|---|---|
| **Ücretsiz** | Takip + dashboard + ayda 10 koç mesajı + manuel haber | ₺0 |
| **Pro** | Sınırsız* koç + proaktif uyarılar + haftalık özet | **~₺149/ay** |

\* "Sınırsız" = adil kullanım (ör. 200 tur/ay) — marjı korumak için **rate-limit
şart** (1000 tur/ay yapan power-user maliyeti ₺400'e çıkar).

### Brüt marj (Pro, ₺149/ay)

| Kullanıcı tipi | Gelir | LLM maliyeti | Brüt marj |
|---|---|---|---|
| Tipik (100 tur) | ₺149 | ~₺40 | **~₺109 (%73)** |
| Ağır (300 tur) | ₺149 | ~₺120 | ~₺29 (%19) → **cap koy** |

## Kritik uyarılar

- **FX riski:** maliyet USD, gelir TRY. TL değer kaybederse marj erir — fiyatı
  TL'de sabit tutarsan riski sen taşırsın. Periyodik fiyat gözden geçirmesi planla.
- **Adil kullanım/rate-limit olmadan** birkaç power-user marjı yer. v1'de tur
  sayacı + aylık cap ekle.
- Gemini fiyatları ve `news_api`/Neon ücretli katmanları değişir — bu modeli
  çeyrekte bir güncelle.
- Bu model **marjinal** maliyet içindir; senin zamanın, sabit hosting tabanı,
  pazarlama (CAC) ayrı. Başabaş = (sabit giderler) / (kullanıcı başı brüt marj).
