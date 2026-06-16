# FinCoach Backend İyileştirme Rehberi

> Haber pipeline'ı + AI/NLP odaklı, mevcut mimariye (FastAPI + LangGraph + Gemini) özel yol haritası.
> Tarih: 2026-06-10

---

## 1. Mevcut Durum Analizi

Kod tabanı incelemesinden çıkan tablo:

| Bileşen | Mevcut durum | Sorun |
|---|---|---|
| Haber kaynakları | NewsAPI + RSS (Google News, Yahoo Finance, CoinDesk, Cointelegraph) — `tools/news_tools.py` | Talep anında (on-demand) çekiliyor; her chat turu canlı HTTP isteği bekliyor |
| Cache | `joblib.Memory(".joblib_cache")` sadece `_fetch_newsapi` üzerinde | **TTL yok** — eski haberler süresiz cache'te kalıyor. RSS hiç cache'lenmiyor |
| HTTP | Senkron `requests` + `feedparser.parse(url)` | RSS istekleri seri; 3-4 feed = 3-4 × ağ gecikmesi. `feedparser.parse(url)`'de timeout kontrolü yok |
| Dedup | Birebir başlık eşleşmesi (`_dedupe`) | Aynı haberin farklı başlıklı kopyalarını yakalayamıyor |
| Sentiment | Tamamen LLM (Gemini prompt: "tag sentiment") — `agents/news_sentiment.py` | Her tur LLM çağrısı; tutarsız, ölçülemez, toplu işlenemez |
| Kalıcılık | Haber için DB tablosu yok | Geçmiş analiz, trend takibi, tekrar sorgu imkânsız |
| Arka plan iş | Sadece TEFAS prewarm thread'i (`main.py` lifespan) | Haber için periyodik toplayıcı yok |

**Ana fikir:** "Haberlere daha hızlı erişim" sorununun kökü kaynak hızı değil, *mimari*: haber, kullanıcı sorduğu anda çekiliyor. Çözüm — haberleri arka planda sürekli topla, zenginleştir (sentiment/kategori/embedding), DB'ye yaz; agent ve UI sadece DB'den okusun. Yanıt süresi saniyelerden milisaniyelere düşer.

---

## 2. Haber Pipeline Yol Haritası

### Faz 1 — Hızlı Kazanımlar (yarım gün)

**1a. joblib cache'e TTL ekle.** joblib `Memory` TTL desteklemez; en basit çözüm cache anahtarına zaman dilimi katmak (TEFAS'taki `today_iso` deseninin aynısı):

```python
@_cache.cache
def _fetch_newsapi(q: str, page_size: int = 10, *, time_bucket: str = "") -> list[dict]:
    ...

def fetch_newsapi(q: str, page_size: int = 10) -> list[dict]:
    # 15 dakikalık dilim → en fazla 15 dk bayat sonuç
    bucket = datetime.now().strftime("%Y%m%d%H") + str(datetime.now().minute // 15)
    return _fetch_newsapi(q, page_size, time_bucket=bucket)
```

**1b. RSS isteklerini paralelleştir + timeout.** `feedparser.parse(url)` yerine içeriği `httpx` ile çek, sonra parse et:

```python
import asyncio, httpx, feedparser

async def _fetch_many(urls: list[str]) -> list[bytes]:
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(client.get(u) for u in urls), return_exceptions=True
        )
    return [r.content for r in results if not isinstance(r, Exception)]
# feedparser.parse(bytes) ağ erişimi yapmaz — sadece parse eder.
```

Not: `create_react_agent` senkron tool'ları thread'de çalıştırdığı için mevcut yapı event loop'u kilitlemiyor; ama seri istekler yine yavaş. Paralelleştirme tek başına 3-4× hız kazandırır.

**1c. Türkçe kaynak listesini genişlet.** Şu an Türkçe haber tek kanaldan (Google News RSS) geliyor. Ücretsiz eklenebilecekler:

- Investing.com Türkiye RSS: `https://tr.investing.com/rss/news.rss` (ekonomi/piyasa alt feed'leri var — [liste](https://tr.investing.com/webmaster-tools/rss))
- NTV Ekonomi RSS: [ntv.com.tr/rss](https://www.ntv.com.tr/rss)
- Bloomberg HT (resmî RSS yok; Google News `site:bloomberght.com` sorgusu ile dolaylı erişim)
- KAP (Kamuyu Aydınlatma Platformu) bildirimleri — BIST hisseleri için *birincil* kaynak; kap.org.tr'nin günlük bildirim sayfası/feed'i ücretsiz

**1d. GDELT'i yedek/genişlik kaynağı olarak ekle.** [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) tamamen ücretsiz, anahtar gerektirmez, 65+ dilde (Türkçe dâhil) ~15 dakikada bir güncellenir:

```
https://api.gdeltproject.org/api/v2/doc/doc?query=ASELSAN&mode=artlist&format=json&timespan=24h
```

NewsAPI'nin free-tier kısıtlarına (24 saat gecikme, 100 istek/gün) takıldığınız her yerde GDELT devreye girebilir.

### Faz 2 — Arka Plan Toplayıcı (1-2 gün) ⭐ en yüksek etki

Kullanıcı beklerken haber çekmek yerine, sidecar açıkken periyodik topla.

**2a. DB modeli** (`app/db/models.py`):

```python
class NewsArticle(Base):
    __tablename__ = "news_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(index=True)
    snippet: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    tickers: Mapped[str | None] = mapped_column(String(256))    # "ASELS.IS,THYAO.IS"
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    sentiment: Mapped[str | None] = mapped_column(String(16))   # positive/neutral/negative
    sentiment_score: Mapped[float | None]
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # dedup için
    fetched_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

(Şema değişikliği = prototip kuralı gereği `fincoach.db` silinip `init_db()` ile yeniden oluşturma — silmeden önce onay al.)

**2b. Zamanlayıcı.** Yeni bağımlılık olarak `apscheduler>=3.10` ekleyin; lifespan'a:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(poll_all_feeds, "interval", minutes=10, max_instances=1)
scheduler.start()   # lifespan startup'ta; shutdown'da scheduler.shutdown()
```

Redis/Celery/RabbitMQ **gerekmez** — tek süreçli masaüstü sidecar için APScheduler + asyncio doğru ölçek. Kuyruk sistemleri ancak çok sunuculu, çok işçili dağıtık yükte anlamlı.

**2c. Koşullu GET (conditional requests).** RSS sunucularına saygılı ve hızlı erişim için ETag/Last-Modified saklayın; feed değişmediyse 304 döner, bant genişliği ≈ 0:

```python
class FeedState(Base):
    __tablename__ = "feed_state"
    url: Mapped[str] = mapped_column(primary_key=True)
    etag: Mapped[str | None]
    last_modified: Mapped[str | None]

headers = {}
if state.etag: headers["If-None-Match"] = state.etag
if state.last_modified: headers["If-Modified-Since"] = state.last_modified
resp = await client.get(feed_url, headers=headers)
if resp.status_code == 304:
    return []  # değişiklik yok
```

**2d. Tool'u DB-öncelikli yap.** `search_news` önce `news_articles`'a baksın (son 24-48 saat, ticker/kategori filtresi); boşsa mevcut canlı yola düşsün. Agent yanıt süresi haber turlarında belirgin kısalır, NewsAPI kotası da korunur.

### Faz 3 — Akıllı Deduplication (yarım gün)

Üç katman, ucuzdan pahalıya:

1. **URL kanonikleştirme** — `utm_*` parametrelerini temizle, `url` üzerindeki unique constraint gerisini halleder.
2. **Normalize başlık hash'i** — küçük harf + noktalama temizliği + `hashlib.sha1`; mevcut `_dedupe`'un kalıcı hâli (`content_hash` kolonu).
3. **Embedding benzerliği** (yakın-kopya yakalar: "Fed faiz indirdi" vs "Fed'den 25 baz puanlık indirim") — ChromaDB zaten projede var:

```python
# Toplayıcı, yeni makaleyi embed edip Chroma'ya yazar:
emb = genai_client.models.embed_content(
    model="gemini-embedding-001", contents=article.title + " " + (article.snippet or "")
).embeddings[0].values
hits = news_collection.query(query_embeddings=[emb], n_results=1)
if hits["distances"][0] and hits["distances"][0][0] < 0.15:  # eşik: deneyerek ayarla
    mark_duplicate(article)
```

`gemini-embedding-001` ücretsiz katmanda kullanılabilir; ücretli geçişte $0.15/1M token, Batch API ile $0.075/1M ([fiyatlandırma](https://ai.google.dev/gemini-api/docs/rate-limits)). 10 dakikada ~50 başlık embed etmek free-tier limitlerine rahat sığar.

---

## 3. AI/NLP İyileştirmeleri

### 3.1 Sentiment: LLM-prompt'tan yapılandırılmış pipeline'a

Şu an sentiment, news_sentiment agent'ının serbest metin çıktısının içinde. İki seçenek; **ikisi birlikte** de kullanılabilir:

**Seçenek A — Gemini ile toplu, yapılandırılmış skorlama (önerilen başlangıç).** Yeni bağımlılık yok, mevcut stack:

```python
from pydantic import BaseModel

class HeadlineSentiment(BaseModel):
    index: int
    sentiment: Literal["positive", "neutral", "negative"]
    score: float          # -1..1
    category: Literal["earnings", "macro", "regulation", "ma", "crypto", "market", "other"]

class BatchResult(BaseModel):
    items: list[HeadlineSentiment]

# Toplayıcı her döngüde YENİ makaleleri TEK çağrıda skorlar (30-50 başlık/istek).
# Determinizm için yapılandırılmış sıcaklık kullanın (settings'te zaten var):
llm = get_llm(temperature=settings.gemini_structured_temperature).with_structured_output(BatchResult)
```

Avantaj: tur başına değil, *makale başına bir kez* skorlanır ve DB'de saklanır. Agent artık sentiment hesaplamaz, hazır etiketi okur — hem hızlı hem tutarlı. `gemini-3.1-flash-lite` ile maliyet ihmal edilebilir; gecikmesi önemsiz işler için Gemini Batch API %50 daha ucuz.

**Seçenek B — Lokal FinBERT (İngilizce başlıklar için, tamamen ücretsiz/offline).** [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert) veya tona duyarlı [yiyanghkust/finbert-tone](https://huggingface.co/yiyanghkust/finbert-tone); daha hafif istiyorsanız HF'deki distilroberta tabanlı finansal sentiment modelleri. CPU'da hız için ONNX Runtime + kantalama:

```bash
uv add optimum[onnxruntime] transformers
```

```python
from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer, pipeline

model = ORTModelForSequenceClassification.from_pretrained("ProsusAI/finbert", export=True)
tok = AutoTokenizer.from_pretrained("ProsusAI/finbert")
clf = pipeline("text-classification", model=model, tokenizer=tok)
clf(["Apple beats Q2 earnings expectations"])  # ~5-15 ms/başlık CPU'da
```

Dikkat: FinBERT İngilizce'dir. Türkçe başlıklar için HF'de Türkçe sentiment modelleri mevcut (ör. BERTurk tabanlı genel sentiment modelleri — finansal alana özel Türkçe model zayıf), bu yüzden **Türkçe için pratik yol Seçenek A** (Gemini çok dilli ve finans bağlamını anlıyor). Mantıklı hibrit: `lang=="en"` → lokal FinBERT (ücretsiz, hızlı), `lang=="tr"` → Gemini batch.

Karar tablosu:

| Kriter | A: Gemini batch | B: Lokal FinBERT/ONNX |
|---|---|---|
| Ek bağımlılık | Yok | torch/onnxruntime (~500MB+, MSI boyutunu şişirir) |
| Türkçe | ✅ İyi | ❌ Yok (finansal) |
| Maliyet | ~Sıfır (flash-lite) ama kota tüketir | Sıfır, offline |
| Tutarlılık | structured output ile iyi | Deterministik, ölçülebilir |
| Tavsiye | **Önce bunu yap** | İngilizce hacim artarsa ekle |

### 3.2 Kategorizasyon

Ayrı model gerekmez — 3.1'deki structured output şemasına `category` alanı eklemek (yukarıda gösterildi) tek çağrıda hem sentiment hem kategori verir. Daha sonra ölçek büyürse: makale embedding'leri zaten Chroma'da olacağı için **embedding + kNN** ile sıfır maliyetli sınıflandırıcı kurulabilir (etiketli birkaç yüz örnek yeter, scikit-learn `KNeighborsClassifier`).

### 3.3 Özetleme

- Tek makale/kısa liste: `gemini-3.1-flash-lite` zaten en ucuz seçenek — değiştirmeyin.
- "Günün özeti" gibi çok makaleli özetler: map-reduce — toplayıcı her makaleye 1-2 cümlelik özet yazar (3.1'deki batch çağrısına `summary: str` alanı ekleyin), gün sonu özeti bu mini-özetlerden üretilir. Bağlam penceresine yüzlerce tam makale yüklemekten hem ucuz hem hızlıdır.
- Lokal alternatif (gerekirse): HF `sshleifer/distilbart-cnn-12-6` — ama B seçeneğindeki boyut maliyeti burada da geçerli; Gemini'de kalın.

### 3.4 Hedef mimari

```
                 ┌──────────────── Arka plan (APScheduler, 10 dk) ───────────────┐
RSS/NewsAPI/GDELT → fetch (httpx, paralel, 304) → dedup (hash+embedding)
   → enrich (Gemini batch: sentiment+kategori+özet) → SQLite news_articles + Chroma
                 └────────────────────────────────────────────────────────────────┘
                                            ↓ (ms-düzeyi okuma)
   /chat → news_sentiment agent → search_news (DB-öncelikli) → hazır etiketli haber
   /news/feed (yeni endpoint) → UI dashboard haber paneli
```

Bu, "AI'ı daha etkili kullanmak"ın özü: LLM'i istek anında her şeyi yapan darboğaz olmaktan çıkarıp, arka planda veri zenginleştiren + ön planda hazır veriyi yorumlayan iki ayrı role bölmek.

---

## 4. Entegrasyon Adımları (mevcut konvansiyonlara göre)

1. **Servis**: `app/services/news_collector.py` — poll/dedup/enrich döngüsü (CLAUDE.md'deki servis düzenine uygun).
2. **Tool**: `app/tools/news_tools.py` içinde `search_news`'u DB-öncelikli yap; imza değişmez, agent prompt'una dokunmak gerekmez.
3. **Endpoint**: `app/routers/news.py` → `GET /news/feed?ticker=&category=&since=` + `src/lib/api.ts`'e typed wrapper. Dashboard'a haber paneli için hazır.
4. **Ayarlar**: `settings.py`'ye `news_poll_minutes: int = 10`, `news_feeds: str` (virgülle ayrık URL listesi, .env'den özelleştirilebilir).
5. **Test**: toplayıcıyı saf fonksiyonlara bölün (`parse → dedup → enrich`), ağ kısmını `pytest -m network` işaretiyle ayırın.
6. **Hata yolu**: yeni endpoint'lerde `_safe_error_message` kullanmayı unutmayın (API anahtarı sızıntısı koruması).

---

## 5. Performans Notları (kısa)

- **httpx singleton**: her istekte yeni `AsyncClient` açmayın; lifespan'da bir tane oluşturup paylaşın (connection pooling + keep-alive).
- **SQLite**: `PRAGMA journal_mode=WAL` + `published_at`, `category`, `content_hash` indeksleri (modelde mevcut). Tek kullanıcılı masaüstü için PostgreSQL'e *geçmeyin*; Neon yolu zaten opsiyonel duruyor.
- **Elasticsearch/MongoDB gerekmez**: on binlerce makalede SQLite `LIKE`/FTS5 yeterli. Anlamsal arama ihtiyacı zaten Chroma ile karşılanıyor.
- **CDN/Redis gerekmez**: lokal sidecar'da ağ kenarı yok; mevcut üç katman (per-request ContextVar + joblib disk + yeni DB) yeterli.

---

## 6. Sorularınızın Geri Kalanına Kısa Cevaplar

**Teknoloji seçimi (Node/Go/Rust?)** — Kalın: Python + FastAPI. AI/LangChain ekosistemi Python'da; Go/Rust'ın getireceği ham hız, darboğazınız olan ağ G/Ç ve LLM gecikmesinde hiçbir şey kazandırmaz. Yeniden yazım = sıfır özellik, yüksek risk.

**Mikroservis?** — Hayır. Tek kullanıcılı masaüstü sidecar için mikroservis saf maliyettir (dağıtım, IPC, hata yüzeyi). Doğru hedef *modüler monolit*: zaten `agents/ tools/ services/ routers/` ayrımınız bu. Mikroservis ancak bağımsız ölçeklenen, ayrı ekiplerce geliştirilen bileşenler olduğunda anlamlıdır.

**Docker/Kubernetes?** — Tauri sidecar dağıtımı MSI ile yapılıyor; Docker burada devreye girmez. Backend'i ileride bir sunucuya (çok kullanıcılı SaaS) taşırsanız tek bir Dockerfile yeterli; K8s o ölçekte bile erken.

**GraphQL?** — Gerek yok. Tek tüketicili (kendi UI'niz) API'de REST + typed `api.ts` wrapper'ları daha az karmaşıklıkla aynı işi görür.

**Kuyruk (Redis/RabbitMQ)?** — Tek süreçte APScheduler + asyncio yeterli (bkz. 2b). Kuyruk, işi *başka makinelere* dağıtmanız gerektiğinde alınır.

**Web scraping etik/yasal sınırlar** — robots.txt'ye uyun, RSS/resmî API varken HTML kazımayın, istek aralığı koyun (feed başına ≥5 dk), `User-Agent` belirtin, içeriği yeniden yayınlamayın (başlık+link+kısa alıntı gösterin, tam metni değil — telif). KAP/TEFAS gibi kamu kaynakları en güvenli alan. Bu hukuki tavsiye değildir; ticarileşme aşamasında kaynakların kullanım şartlarını kontrol edin.

**Ücretsiz veri setleri/öğrenme kaynakları** — Financial PhraseBank ve FiQA (finansal sentiment, HF Datasets'te), Kaggle finans haber setleri; kütüphane olarak scikit-learn (klasik ML), HF Transformers (NLP), PyTorch (özel model gerekirse — şu an gerekmiyor). Başlangıç: HF'nin ücretsiz [NLP kursu](https://huggingface.co/learn).

---

## 7. Önerilen Uygulama Sırası

| # | İş | Efor | Etki |
|---|---|---|---|
| 1 | Faz 1a-1b: TTL + paralel RSS + timeout | ~2 saat | Anında hız kazancı |
| 2 | Faz 1c-1d: TR kaynakları + GDELT | ~2 saat | Kapsam, özellikle BIST/TEFAS |
| 3 | Faz 2: `NewsArticle` + APScheduler toplayıcı + DB-öncelikli tool | 1-2 gün | **En büyük kazanç** — ms-düzeyi haber erişimi |
| 4 | 3.1-A: Gemini batch sentiment+kategori+özet | ~yarım gün | AI'ın etkin kullanımı; agent hızlanır |
| 5 | Faz 3: embedding dedup (Chroma) | ~yarım gün | Çok kaynaklı temiz feed |
| 6 | `/news/feed` endpoint + UI paneli | ~yarım gün | Kullanıcıya görünür değer |
| 7 | (Opsiyonel) FinBERT/ONNX lokal sentiment | 1 gün | Offline/kota bağımsızlığı |

---

## 8. Kaynaklar

- [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) — ücretsiz, anahtarsız haber arama
- [Investing.com TR RSS listesi](https://tr.investing.com/webmaster-tools/rss) · [NTV RSS](https://www.ntv.com.tr/rss)
- [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert) · [yiyanghkust/finbert-tone](https://huggingface.co/yiyanghkust/finbert-tone) · [FinBERT makalesi](https://arxiv.org/pdf/1908.10063)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) · [Gemini Embedding duyurusu](https://developers.googleblog.com/gemini-embedding-available-gemini-api/)
- [NewsData.io ücretsiz haber API karşılaştırması](https://newsdata.io/blog/best-free-news-api/) · [APITube free tier](https://apitube.io/free-news-api)
- [HF NLP kursu](https://huggingface.co/learn) · Financial PhraseBank / FiQA (HF Datasets)

> Not: Bu doküman hackathon prototipi bağlamına göre kalibre edilmiştir; "yapma" denilen şeyler (mikroservis, K8s, Redis) ölçek değişirse yeniden değerlendirilmelidir.

