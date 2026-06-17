# AI Kalite Eleştirisi + Düzeltmeler

> "Gerçekten çalışıyor mu, müşterinin ihtiyacını karşılıyor mu?" sorusunu
> ölçülebilir hale getirmek için yapılan çalışmanın özeti. İki kısım: (1) tüm
> sohbet ajanlarının okunup eleştirilmesi, (2) güvenli, doğrulanabilir
> düzeltmelerin uygulanması. Yargı gerektiren prompt-kalite değişiklikleri
> `backend/evals/` harness'i ile ölçülerek yapılmalı (canlı anahtar gerekir).

## Yöntem

- 11 ajan dosyası (strateji, sentez, danışman + 7 uzman + yardımcılar) baştan
  sona okundu; iki bağımsız ajan eleştirisi + web araştırması
  (LLM-as-judge / rubric tasarımı, finans asistanı UX) ile çapraz kontrol edildi.
- **Kritik kısıt:** bu ortamda `GEMINI_API_KEY` yok → canlı sohbeti çalıştırıp
  gerçek cevapları ölçemedim. Bu yüzden teslim edilen asıl yapı **eval harness'i**
  (golden QA setleri + runner + rubrik temelli LLM-judge): kullanıcı kendi
  anahtarıyla çalıştırıp "çalışıyor mu / kullanılabilir mi" sorusunu ölçer,
  iyileştirmeleri bu döngüyle doğrular. Bkz. `backend/evals/README.md`.

## Genel değerlendirme

Sistem sanıldığından **olgun**: sentez (synthesizer) ve strateji (strategist)
promptları zaten gelişmiş — ses tonu, uzunluk kuralları, takip-tespiti, anafora,
regülasyon koruması (spesifik AL tavsiyesi yok), para birimi/dil aynalama içeriyor.
Bu yüzden **körü körüne büyük prompt rewrite'ı yapmak risklidir** — ölçüm
döngüsü olmadan kaliteyi düşürebilir. Doğru sıra: önce harness, sonra güvenli
düzeltmeler, sonra eval ile doğrulanmış iyileştirmeler.

## Uygulanan düzeltmeler (güvenli + test edildi)

| # | Dosya | Sorun | Düzeltme |
|---|---|---|---|
| 1 | `risk_profiler.py` | **Veri bozulması bug'ı:** `_UPDATE_RE` "risk profilimi **3** kademe değiştir" cümlesini yakalayıp risk skorunu sessizce **3** yapıyordu. | Regex sıkılaştırıldı: sayı açık bir "risk skoru" ifadesine bağlı olmalı; "kademe/basamak/adım" gibi adım ifadeleri reddediliyor. **Birim test eklendi.** |
| 2 | `risk_profiler.py` | Türk kullanıcıya İngilizce + keyfi "/125" sızan `Risk score: 72/125` özeti. | Özet UI diline göre yerelleştirildi (`Risk skorun: 72/125 — dengeli …`). Test eklendi. |
| 3 | `budget_coach.py` | `_is_roast` her turda hata-yakalamasız DB sorgusu açıyor → DB hatası tüm turu çökertir. | `try/except → False` (roast bayrağı kozmetik, turu asla bozmamalı). |
| 4 | `budget_coach.py` | Roast promptunda **dil kuralı yok** + tek örnek İngilizce → Türk kullanıcıya İngilizce roast. | Promtta dil kuralı + ₺ etiketi + Türkçe örnek eklendi. |
| 5 | `news_sentiment.py` | Agresif profil bloğu söylentileri "alpha opportunities" / "high-conviction bets" olarak çerçeveliyordu — kendi "haber sun, tavsiye verme" kuralıyla çelişen **regülasyon riski**. | Spekülatif çerçeveleme kaldırıldı (nötr haber sunumu); ayrıca eksik **dil kuralı** eklendi. |

Doğrulama: `ruff` temiz, `uv run pytest -m "not network"` → **84 passed**.

## Önerilen ama ERTELENEN (eval ile doğrulanmalı)

Bunlar yargı/kalite değişiklikleri — körlemesine uygulamak yerine harness ile
A/B ölçülmeli (regresyon riski var):

- **`market_data.py` — ABD-merkezli referans listesi.** Ticker belirtilmeyince
  `SPY/QQQ/VTI` öneriyor; Türk yatırımcı bunları kolay alamaz. TEFAS/BIST-öncelikli
  bir baz öneri + her fiyatın para birimini belirtmesi gerekir. (Wedge ile birebir.)
- **`advisor.py` — TR varlık-sınıfı gerçekliği + disclaimer.** Bantlar VOO/VTI
  ve ABD tahvil/nakit mantığına göre; TL enflasyonu/FX dikkate alınmıyor. Şemada
  `disclaimer` alanı yok (UI disclaimer'ı var ama sentez closer'ı bilinçli kapatıyor
  — değiştirmeden önce ürün kararı gerekir).
- **`memory.py` — belirsiz-niyet fallback'i zayıf.** İlgi eşiği + bir netleştirme
  sorusu eklenmeli (şu an zayıf eşleşmeyi "anı" gibi sunabiliyor).
- **`_helpers.normalize_content`** — yalnızca metin-dışı parçalardan oluşan içerik
  için sessizce `""` dönüyor; nadir durumda bir yanıtı "boş" sayabilir.
- **`market_data` ölü `scan_rumors`** — promptta "veri kaynağı kaldırıldı" diyor
  ama hâlâ bağlı; `news_sentiment` ise canlı sayıyor. Tutarlılık netleştirilmeli.

## İyileştirme döngüsü (kullanıcı için)

1. `uv run python -m evals.run_evals` → `uv run python -m evals.grade run_*.json`
2. `report.md`'de en zayıf boyut/itemleri gör.
3. Sorumlu ajanın **promptunu** düzelt (yukarıdaki ertelenenlerden başla).
4. Aynı seti tekrar çalıştır → skor yükseldi mi, regresyon var mı doğrula.
5. Koçu utandıran her gerçek soruyu yeni bir golden item olarak ekle.
