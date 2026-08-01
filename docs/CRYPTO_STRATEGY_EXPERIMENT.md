# Kripto strateji deneyi — 15dk / 30dk / 1sa / 4sa

Bu doküman, "hangi strateji hangi zaman diliminde kâr ettiriyor?" sorusunu
dürüst şekilde cevaplamak için kurulan deneysel düzeneği ve bulguları anlatır.

Deney açıkça **negatif sonuç verebilir** ve bu bir başarısızlık değildir. Aksine:
bu düzeneğin asıl işi, güzel görünen ama yanlış olan sonuçları yakalamaktır.
Şimdiye kadarki en değerli çıktıları da tam olarak bunlar oldu.

## Düzenek

```
exchange.py      15dk/30dk/1sa/4sa mumları — Binance.US / OKX / Coinbase
   ↓             (kapanmamış bar atılır, mükerrer bar temizlenir, kalite kapıları)
tournament.py    coin × zaman dilimi × strateji × parametre × long-flat/long-short
   ↓             walk-forward + purged/embargo, üç bağımsız test
paper.py         kazananları İLERİ doğru çalıştır — asıl kanıt burada
   ↓
run_experiment.py + experiment_loop.sh   sabit uzunlukta pencere, 15dk'da bir döngü
```

**Turnuva seçimdir, kağıt defter kanıttır.** Backtest istediğin sonucu verene
kadar tekrar çalıştırılabilir; ileri doğru tutulan bir günlük çalıştırılamaz.
Kağıt defterin işlem gördüğü her bar, strateji seçildiğinde henüz var olmayan
bir bardır — düzeltilecek seçim yanlılığı yoktur.

## Ölçüm kararları ve gerekçeleri

| Karar | Neden |
|---|---|
| Sinyal bir bar kaydırılır | t barında hesaplanan sinyal ancak t→t+1 getirisini kazanabilir. Tek yerde yapılır (`align_positions`), bir test son barın sinyalinin **ulaşılamaz** olduğunu kanıtlar |
| Maliyet opsiyonel değil | 10bps komisyon + 5bps slippage = 30bps gidiş-dönüş. Brüt−net farkı `cost_drag` olarak ayrı raporlanır |
| Çoklu test **tüm turnuva** üzerinden | Kazanan ~2500 denemenin maksimumudur. Onu kendi 6'lık ızgarasına göre deflate etmek kendini kandırmaktır |
| Al-tut **aynı barlarda** ölçülür | Örneklem-dışı kaydı tam-örneklem al-tut ile karşılaştırmak elmayla armuttur; fark çoğunlukla test edilmemiş barlardaki piyasa hareketidir |
| Üç testin **üçü birden** geçmeli | Turnuva-geneli Deflated Sharpe + PBO + blok bootstrap p-değeri. Her biri tek başına kandırılabilir |
| Kalite kapıları | Donmuş emir defteri, mean-reversion backtest'inde muhteşem görünür ve işlem yapılamaz |
| Fizibilite taraması | Bir hücrenin maliyeti karşılamak için gereken **brüt** Sharpe'ı; 1.5'in üstündekiler daha fitlenmeden elenir. Aritmetik — kârlılığa hiç bakmaz, dolayısıyla veri madenciliği suçlaması yapılamaz |

## Bulunan hatalar

İkisi de **sessizdi**: exception yok, uyarı yok, makul görünen bir sayı. Aranan
hata sınıfı tam olarak budur — çöken kod ilginç değildir, doğru görünen yanlış
sayı ilginçtir.

### 1. Deflated Sharpe yapısal olarak sıfırdı

`scorecard.deflated_sharpe_ratio(..., variance_trials=1.0)` — bu varsayılan
"denemeler arası Sharpe varyansı 1" demektir ve **yıllık** Sharpe'lar için
doğrudur. Motor ise **bar-başı** Sharpe geçiyordu. 15dk barda bu, referans
eşiğini bar-başı 3.5'e, yani **yıllık ~660 Sharpe**'a çıkarıyor.

Sonuç: her hücrede `DSR = 0.0000`, ve `survives` kapısı `dsr > 0.95` istediği
için **hiçbir koşulda hayatta kalan raporlanamıyordu.**

İlk tam çalıştırma usulüne uygun şekilde "512 hücrenin 0'ı hayatta kaldı" dedi
ve titiz göründü. Aslında bu, birim uyuşmazlığının ürettiği bir yanlış
negatifti — dürüst bir null sonuçtan ayırt edilemez, ve bu yüzden mevcut en
kötü hata biçimi.

**İpucu oradaydı:** o çalıştırmadaki `dsrT` sütununun tamamı 0.0'dı, +8744%'lik
satır dahil. Gözden kaçtı.

Düzeltme: `backtest.trial_variance()` deneme Sharpe'larının varyansını **aynı
bar-başı birimde** ölçer. Artık DSR gerçek değerler veriyor (0.0722, 0.0478,
0.0288…) ve PBO 0.75 okuyor — "bu seçim büyük ölçüde gürültü" diyen dürüst bir
cevap. İki regresyon testi birimleri sabitliyor.

### 2. +8744%'lik "edge" ölü bir emir defteriydi

İlk turnuva `TRX/15m/bollinger_reversion`'ı örneklem-dışı **+8744%** ile taçlandırdı.

Binance.US'te o barların:
- **%68'i sıfır getirili** (fiyat hiç hareket etmemiş)
- **%64'ü sıfır hacimli** (hiç işlem olmamış)
- medyan bar aralığı **%0.000**

Fiyat saatlerce donuyor, sonra biri nihayet işlem yapınca %11 sıçrıyor.
Mean-reversion kuralı bunu "dip al, tepe sat" olarak görüyor — gerçekte
topladığı şey ölü bir defterin alış-satış makası. Kimse bunu işleme çeviremez.

Aynı çift OKX'te %3.15 stale ve %0.071 medyan aralık — gerçek bir piyasa.
**Sorun coin değil borsaydı**, ve sebebi benim kaynak seçimimdi: Binance.US
sayfalama hızı yüzünden öncelikliydi, yani en çok önem taşıyan çiftlerde en
kötü borsayı seçiyordum.

Ayrıca TRX 30dk/1sa serisinde tek barda **+385.59%** bulundu (0.0670 → 0.3252) —
bir yeniden değerleme ya da veri ekleme hatası, getiri değil. Böyle bir kopuş
serideki her long kurala bedava %385 hediye eder.

Düzeltme: `exchange.assess()` her seriyi notlandırır (stale oranı, sıfır hacim
oranı, medyan bar aralığı, bölünme boyutunda sıçramalar) ve **en derin değil en
likit** kaynağı seçer. Düzeltmeden sonra TRX, HYPE, DOGE ve BNB otomatik olarak
OKX'e geçti ve evrendeki her coin kapılardan geçti.

## Bulgu 3: liderlik tablosu KARARLI — ve bu bir edge kanıtı değil

Dört turnuva koşusunun top-10'ları birbirinden tamamen farklı çıktı (son ikisinde
kesişim 0/10). İlk okuma "seçim gürültü, tablo hiç sabit kalmıyor" idi. **Bu okuma
yanlıştı ve temiz test onu çürüttü.**

Koşular arasında kodu da değiştirmiştim (DSR havuzlama düzeltmesi sıralamayı,
fizibilite ve net-seçim düzeltmeleri hangi parametrelerin kazandığını değiştirdi),
yani 0/10'un kaynağı belirsizdi. Kontrollü test: **aynı kod, aynı sekiz coin,
~40 dakika arayla iki koşu.**

| | koşu 4 | koşu 5 |
|---|---|---|
| konfigürasyon | 4352 | 4352 |
| PBO | 0.5774 | 0.5754 |
| top-10 kesişimi | — | **9/10** |
| coin kesişimi | — | **6/6** |

Yani liderlik tablosu son derece kararlı; önceki 0/10 tamamen kendi
düzeltmelerimden kaynaklanıyordu.

**Ama kararlılık bir edge kanıtı değildir.** Turnuva, neredeyse aynı veri üzerinde
deterministik bir hesap — tekrar üretilebilir olması beklenen davranıştır ve
seçilen kuralın YENİ veriye genelleneceği hakkında hiçbir şey söylemez. Genelleme
sorusunu soran test PBO'dur, ve o 0.577 diyor: örneklem-içi kazanan, örneklem
dışında yarıdan fazla kez medyanın altına düşüyor.

Kaydedilmeye değer çünkü kolay bir yanlış çıkarım: "tablo her koşuda aynı çıkıyor,
demek ki sağlam." Değil — sadece deterministik.

## Zaman dilimi karşılaştırması

Sıralama hatası düzeltildikten sonraki tablo:

| tf | hücre | medyan Sharpe | pozitif | al-tut'u geçen | medyan DSR |
|---|---|---|---|---|---|
| 15dk | 34 | **−1.54** | 5/34 | 24/34 | 0.0040 |
| 30dk | 59 | **−1.00** | 20/59 | 11/59 | 0.0002 |
| 1sa | 79 | **−0.60** | 10/79 | 59/79 | 0.0000 |
| 4sa | 112 | **+0.15** | 41/112 | 16/112 | 0.0000 |

Top-10 ise 5× 15dk + 5× 30dk — hiç 4 saatlik yok. **İkisi çelişmiyor, farklı
şeyler söylüyor:** hızlı zaman dilimlerinde dağılım geniş (çoğu hücre sert
kaybediyor, birkaçı 2.1 Sharpe'a çıkıyor), 4 saatlikte merkezi hafif pozitif ama
uç kazanan yok. Yani hızlıdaki "kazananlar" gürültülü bir dağılımın sağ kuyruğu.

Bir önceki koşuda "top-10'un onu da 4 saatlik" diye raporlanan sonuç, DSR
havuzlama hatasının ürünüydü; liderlik tablosu o sütuna göre sıralandığı için
kendini en-yavaş-önce diziyordu. Medyan gradyanı ise DSR'den bağımsız hesaplandığı
için etkilenmedi ve ayakta kaldı.

Hiçbir hücre üç testin üçünü birden geçmiyor: en yüksek DSR 0.178 (eşik 0.95), en
düşük bootstrap p=0.068, PBO 0.577.

## Kritik değişken: turnover

15dk barda 30bps gidiş-dönüş, BTC'nin tek-bar oynaklığının kabaca **2 katı**.
Gürültüyle dönen bir kural kazanabileceğinden fazlasını ödemek zorundadır.

Bysik & Ślepaczuk'un ölçümü (70.872 saatlik BTC/USDT barı, 27 walk-forward
katmanı): **aynı, değiştirilmemiş** tahmin ARC −%64.0'tan +%65.4'e çıkıyor —
tek fark bir icra bandı eklenmesi, işlem sayısı 10.619'dan 251'e düşüyor. Alfa
iyileşmiyor; turnover onu yemeyi bırakıyor.

Buradan çıkan yapısal içgörü: **15dk meşru bir örnekleme frekansı, gayrimeşru
bir işlem frekansıdır.** Motora eklenen `confirm_bars` (hedef kalıcı olmadan
işlem yapma) ve `min_hold_bars` (açılan pozisyonu en az bu kadar bar tut)
parametreleri tam olarak bunu yapar: 15dk barı okumaya devam ederken efektif
tutma süresini uzatır. İkisi de varsayılan 1 (kimlik dönüşümü), yani bantsız
varyant her zaman ızgarada ve sonuçlar doğrudan karşılaştırılabilir kalır.

## Kağıt defter

- Başlangıç sermayesi sabit, gerçek emir yok.
- Her zaman piyasada: her zaman diliminde **bir long/short kural**. Long/flat bir
  kural düşen piyasanın çoğunu nakitte geçirir — bu ne pozisyon alır ne de
  beceri hakkında bir şey söyler.
- Zaman dilimi başına bir hücre: soru açıkça 15dk/30dk/1sa/4sa karşılaştırması
  olduğu için her birine dilim ayrılır. Tüm slotları en iyi backtest eden zaman
  dilimine yüklemek karşılaştırmayı yok ederdi.
- Pozisyon sinyal dönene kadar açık kalır — 15dk'lık bir kural 15dk sonra
  kapanmak zorunda değildir.
- Yeniden hedeflemeden **önce** mark-to-market: fiyat hareketi onu fiilen taşıyan
  pozisyona yazılır.

### Örneklem büyüklüğü hakkında dürüstlük

8 saat × 15dk = **32 gözlem**. Bu, bir edge'i kanıtlamaya da çürütmeye de
yaklaşmaz; bu ölçekte ortalama getirinin standart hatası, makul her edge'i
gölgede bırakır. `paper.performance()` bunu gömmek yerine `caveat` alanında
açıkça söyler. Kağıt defter bir **kayıt**, kanıt değil.

## Kabul edilen sınırlar

- Bar-kapanışı icra. Bar içi dolum, kısmi dolum, emir defteri derinliği ve düz
  slippage varsayımının ötesinde piyasa etkisi yok.
- Tek enstrüman backtest'i; portföy backtest'i değil.
- **Survivorship bias düzeltilmiyor.** Evren bugün var olan coinlerden seçiliyor.
- Perpetual funding şu an işaretsiz; varsayılan 0 olduğu için mevcut sonuçları
  etkilemiyor ama funding açılırsa short'lar alacakları funding'i öder.
- Opsiyon zinciri veri kaynağı yok.

## Çalıştırma

```bash
cd backend
uv run python scripts/run_experiment.py --tournament   # sadece sıralama
uv run python scripts/run_experiment.py --cycle        # bir adım ilerlet
uv run python scripts/run_experiment.py --report       # durum
./scripts/experiment_loop.sh 8 900                     # 8 saat, 15dk'da bir
```

Çıktılar `backend/data/experiment/` altında (gitignore'da):
`tournament_latest.json`, `tournament_history.jsonl`, `cycles.jsonl`,
`paper_state.json`, `loop.log`.

## Veri kaynakları

| Kaynak | Kullanım | Durum |
|---|---|---|
| Binance.US / OKX / Coinbase | Mum verisi (anahtarsız) | Çalışıyor, kaliteye göre seçiliyor |
| coinranking (RapidAPI) | Coin evreni: market cap + hacim | Çalışıyor |
| coindesk-api1 (RapidAPI) | Canlı fiyat / market breadth | Çalışıyor (`pageSize=50` şart, küçük değerlerde 500 dönüyor) |
| crypto-news-api (RapidAPI) | `/latest`, `/trendTag24h` | Çalışıyor |
| alpha-vantage (RapidAPI) | Bağımsız fiyat çapraz kontrolü | Çalışıyor, sıkı rate limit |
| alternative.me | Fear & Greed | Çalışıyor (anahtarsız) |
| CoinGecko (RapidAPI) | — | Abone ama basic planda veri endpoint'leri 403; sadece `/ping` |
