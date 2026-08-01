# Quant Stack — kütüphane değerlendirmesi ve karar kaydı

Bu doküman, **Awesome-Quant**'ın bu projeye uygulanmış hâlidir. Awesome-Quant bir
kütüphane değil, bir fihristtir; onu "kullanmak" demek, o fihristteki seçenekleri
bu sistemin kısıtlarına göre değerlendirip kararı yazılı bırakmak demektir.

Kaynak repolar:

| Repo | Ne olduğu | Bu projeye katkısı |
|---|---|---|
| [Awesome-Quant](https://github.com/wilsonfreitas/awesome-quant) | Kantitatif finans kütüphaneleri / veri kaynakları fihristi | Bu dokümanın kendisi — değerlendirme çerçevesi |
| [Qlib](https://github.com/microsoft/qlib) (Microsoft) | AI odaklı kantitatif araştırma platformu | Backtest mimarisi: veri katmanı → sinyal → backtest ayrımı |
| [Machine-Learning-for-Trading](https://github.com/stefan-jansen/machine-learning-for-trading) (Jansen) | Uçtan uca ML-for-trading dersi | Walk-forward train/test disiplini, look-ahead ve maliyet ele alışı |
| [GS-Quant](https://github.com/goldmansachs/gs-quant) (Goldman Sachs) | Kurumsal risk analitiği + türev fiyatlama | Risk metrik seti (VaR/CVaR, beta/alfa), portföy optimizasyonu API şekli |
| [Financial-Models-Numerical-Methods](https://github.com/cantaro86/Financial-Models-Numerical-Methods) | Opsiyon fiyatlama / stokastik süreç notebook'ları | Black-Scholes-Merton greeks, implied vol kök bulma, Merton jump-diffusion |

## Değerlendirme kısıtları

Bu bir hackathon prototipi değil de bir ürün gibi paketleniyor ve **iki hedefe**
birden dağıtılıyor: Tauri masaüstü uygulaması (Python sidecar) ve Cloud Run
(`backend/Dockerfile`, `python:3.11-slim` üzerine `uv sync`). Bir bağımlılığın
değerlendirme ölçütleri bu yüzden şunlar:

1. **Paket ağırlığı** — imaj boyutu ve cold start.
2. **Veri gereksinimi** — hazır bir veri dump'ı veya ticari oturum gerektiriyor mu?
3. **Lisans**.
4. **Bakım maliyeti** — pinlenmiş bağımlılıklar mevcut numpy 2.4 / pandas 3.0 ile
   çatışıyor mu?
5. **Kullanılan yüzey** — kütüphanenin yüzde kaçını gerçekten kullanacağız?

## Kararlar

### ❌ Qlib — reddedildi, mimarisi alındı

Qlib'in sunduğu şey (model zoo + backtest + veri katmanı) doğru soruyu soruyor
ama kurulumu ağır, kendi hazırladığı `.bin` veri dump'ını istiyor ve
bağımlılıkları pinli. Cloud Run imajına eklemek ve TEFAS/CoinDesk verisini onun
veri formatına dönüştürmek, elde edilecek faydanın kat kat üstünde.

**Yerine:** `backend/app/quant/backtest.py` — Qlib'in katman ayrımını (veri →
sinyal → backtest → metrik) koruyan, ~450 satırlık vektörize bir motor.

### ❌ GS-Quant — reddedildi, metrik seti alındı

Fiyatlama ve risk fonksiyonlarının büyük kısmı `GsSession` — yani Goldman Sachs
tarafında bir hesap — gerektiriyor. Oturumsuz kullanılabilen yüzey, bizim
ihtiyacımızın küçük bir dilimi.

**Yerine:** `backend/app/quant/risk.py` ve `backend/app/quant/optimize.py` —
GS-Quant'ın rapor ettiği metrik ailesini (VaR/CVaR, beta/alfa/R², tracking error,
etkin sınır) yerel veriden hesaplıyor.

### ❌ PyPortfolioOpt / cvxpy — reddedildi

PyPortfolioOpt tam da istediğimiz şeyi yapıyor, ama cvxpy + osqp/ecos zincirini
getiriyor. İhtiyacımız olan üç problem (min-varyans, maks-Sharpe, risk paritesi)
`scipy.optimize.minimize(method="SLSQP")` ile ~120 satırda çözülüyor ve scipy'ye
zaten başka gerekçelerle ihtiyacımız var.

**Yerine:** `optimize.py`. Ledoit-Wolf daraltma da elle yazıldı (2004 makalesindeki
kapalı form) — PyPortfolioOpt'un `risk_models` modülünün tek gerçekten kritik parçası oydu.

### ❌ vectorbt / backtrader / bt — reddedildi

vectorbt hızlı ama numba getiriyor ve API'si geniş. backtrader event-driven ve
bakımı durgun. Her ikisi de bizim ihtiyacımızdan (tek enstrüman, bar-kapanışı,
uzun/flat) çok daha genel.

### ❌ QuantLib / py_vollib — reddedildi

QuantLib'in C++ derlemesi ve boyutu, Black-Scholes + greeks + Merton sıçrama
serisi için savunulamaz. Bu üçü toplam ~200 satır saf matematik.

**Yerine:** `backend/app/quant/options.py`.

### ❌ statsmodels — reddedildi

Sadece OLS + t-istatistiği için ~30 MB. `np.linalg.lstsq` + `scipy.stats.t`
aynı sayıları veriyor (`risk.py::_ols`), ve testler bunu planted-loading
regresyonlarıyla doğruluyor.

### ❌ Fama-French araştırma faktör serileri — reddedildi

Kenneth French veri kütüphanesinden indirme gerektiriyor: ağ bağımlılığı, ayrı
bir güncelleme yolu ve lisans sorusu.

**Yerine:** `risk.py::FACTOR_PROXIES` — likit ETF'lerden kurulmuş proxy faktörler
(SPY, IWM−SPY, IWD−IWF, MTUM−SPY). Mevcut yfinance yolundan geliyor, yeni veri
sağlayıcı yok. Çıktının `note` alanı bunların araştırma serileri **olmadığını**
açıkça söylüyor.

### ✅ scipy — kabul edildi (tek yeni bağımlılık)

Sadece üç yerde:

| Kullanım | Nerede | Alternatifi neden yetmedi |
|---|---|---|
| `optimize.minimize(method="SLSQP")` | `optimize.py` — long-only kısıtlı MV | Kısıtlı optimizasyonu elle yazmak, yakınsama garantisi olmayan bir projeksiyonlu gradyan demekti |
| `optimize.brentq` | `options.py` — implied vol | Bisection fallback zaten var, ama brentq çok daha hızlı yakınsıyor |
| `stats.t` | `risk.py` — regresyon t-stat / p-değeri | Normal yaklaşım küçük örneklemde yanıltıcı |

Çözümleme doğrulandı: numpy 2.4.4 ile `scipy==1.17.1` temiz çözülüyor.

**Not:** Değerlendirme sırasında "scipy zaten chromadb üzerinden transitif olarak
kurulu" varsayımı yapılmıştı; doğrulama bunun yanlış olduğunu gösterdi
(`import scipy` → `ModuleNotFoundError`). Karar, gerçek maliyeti bilerek verildi.

### ✅ numpy / pandas / numpy-financial — zaten vardı

`app/quant` tamamen numpy üzerine kurulu. pandas hâlâ hiçbir `app/` modülünde
import edilmiyor (sadece yfinance/tefas-crawler üzerinden transitif).

## Repo içinde ne yazıldı

| Modül | Satır | Ne yapar | Kaynak |
|---|---|---|---|
| `app/quant/data.py` | ~150 | Üç fiyat kaynağını tek bir oldest-first numpy arayüzüne indirger; ortak işlem günü kesişimi; downsampling | — |
| `app/quant/backtest.py` | ~450 | Vektörize backtest, look-ahead koruması, maliyetler, walk-forward + purged/embargo, DSR | Qlib, ML4T, López de Prado |
| `app/quant/risk.py` | ~280 | VaR/CVaR/Cornish-Fisher, EWMA vol, beta/alfa/R²/t-stat, capture, faktör regresyonu | GS-Quant, RiskMetrics 1996, Cornish-Fisher 1938 |
| `app/quant/optimize.py` | ~240 | Ledoit-Wolf daraltma, min-varyans, maks-Sharpe, risk paritesi, etkin sınır | Markowitz 1952, Ledoit-Wolf 2004, Michaud 1989, Maillard 2010 |
| `app/quant/options.py` | ~210 | BSM fiyat + greeks, implied vol, Merton jump-diffusion, smile | FMNM, Black-Scholes 1973, Merton 1976 |

Metrik çekirdeği **yeniden yazılmadı**: `sharpe`, `sortino`, `calmar`,
`max_drawdown`, `profit_factor`, `probabilistic_sharpe_ratio`,
`deflated_sharpe_ratio` fonksiyonları `app/eval/scorecard.py`'den import ediliyor.
Teknik gösterge matematiği de öyle — `ema_series`, `rsi`, `macd`, `atr`
`app/tools/crypto_short_term.py`'de kalıyor.

## Neden backtest motoru merkeze kondu

`app/eval/scorecard.py:19-21`, kendi eksiğini zaten yazmış:

> *"a **full** CPCV needs a price-path backtest, which a discrete trade ledger
> doesn't provide — we are honest about that rather than overclaiming."*

Scorecard kapanmış `TradeTarget` kayıtlarını puanlayabiliyordu ama onları
besleyecek bir fiyat yolu yoktu. Qlib ve ML4T'nin özü tam olarak bu. Yeni metrik
eklemedik — mevcut metrik çekirdeğine nihayet gerçek bir getiri serisi verdik.

## Dürüstlük tasarımı

Bir backtest motorunun kolay kısmı sayı üretmektir; zor kısmı yalan söylememesidir.
Üç koruma yapısal olarak kuruldu, kullanıcının seçimine bırakılmadı:

1. **Look-ahead** — pozisyon dizisi tek bir yerde (`align_positions`) kaydırılır;
   `test_final_bar_signal_is_structurally_unreachable` bunu kanıtlıyor.
2. **Maliyet** — `Costs` opsiyonel değil, `cost_drag` ayrı raporlanır.
3. **Çoklu test** — `walk_forward` sadece örneklem dışı sonucu sayar ve Sharpe'ı
   denenen parametre sayısına göre deflate eder. `test_more_trials_never_raises_the_deflated_sharpe`
   bu monotonluğu koruyor.

Ayrıca yetersiz veri hâlinde motor **fold uydurmaz** — `{"ok": False, "reason": ...}`
döner ve UI bunu "örneklem dışı doğrulama yapılamadı" olarak gösterir.

## Bilinen sınırlar

* Bar-kapanışı icra; intrabar dolum, kısmi dolum, emir defteri ve piyasa etkisi yok.
* Tek enstrüman backtest'i — portföy backtest'i değil.
* **Survivorship bias düzeltilmiyor.** Test edilen sembol, kullanıcının bugün
  adını verdiği semboldür; hayatta kalmış olması zaten bir koşullanmadır.
* Opsiyon tarafında **zincir verisi yok** — `price_option` / `implied_volatility`
  kullanıcı girdisiyle çalışan hesap makineleridir. Deribit benzeri bir kaynak
  eklenmeden bunlar canlı fiyatlama yapamaz.
* Ortalama-varyans geçmişi optimize eder; tarihsel ortalama getiriler geleceğin
  zayıf tahminidir. `risk_parity` beklenen getiri kullanmadığı için daha sağlamdır.

## Sonraki adım adayları

* Opsiyon zinciri veri kaynağı (Deribit) → `options.py` hesap makinesinden canlı
  IV yüzeyine geçer.
* Çok-enstrümanlı portföy backtest'i → `optimize.py`'nin ağırlıklarını
  `backtest.py`'ye besleyip yeniden dengeleme maliyetiyle birlikte test etmek.
* `TradeTarget` defteri ile fiyat-yolu backtest'ini birleştirip `scorecard.py`'nin
  purged-k-fold'unu gerçek CPCV'ye yükseltmek.
