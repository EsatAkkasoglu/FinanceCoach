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
| Çoklu test **tüm turnuva** üzerinden | Kazanan 4352 denemenin maksimumudur. Onu kendi 6'lık ızgarasına göre deflate etmek kendini kandırmaktır |
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

## Zaman dilimi karşılaştırması (nihai koşu)

8 coin × 4 zaman dilimi × 8 strateji × long-flat/long-short = **512 hücre**.
Fizibilite taraması 6616 parametre setinin 2264'ünü daha fitlenmeden eledi;
kalan **4352 konfigürasyon** backtest edildi. 228 hücrede hiçbir parametre seti
maliyeti karşılayamadı, dolayısıyla **284 hücre** değerlendirilebildi.

Aşağıda "pozitif" = örneklem-dışı **net** getiri > 0; "al-tut'u geçen" =
örneklem-dışı net getiri, **aynı barlardaki** al-tut getirisinden yüksek.

| tf | hücre | medyan Sharpe | pozitif | al-tut'u geçen | medyan yerel DSR | medyan al-tut | medyan fark |
|---|---|---|---|---|---|---|---|
| 15dk | 34 | **−1.46** | 5/34 | 24/34 | 0.073 | −19.5% | **+7.3 pp** |
| 30dk | 59 | **−1.00** | 22/59 | 11/59 | 0.052 | −7.9% | −11.9 pp |
| 1sa | 79 | **−0.60** | 10/79 | 59/79 | 0.052 | −45.9% | **+10.2 pp** |
| 4sa | 112 | **+0.15** | 42/112 | 22/112 | 0.156 | **+43.1%** | −55.8 pp |

### Bu tablo tek bir sıralama vermiyor — iki farklı sıralama veriyor

**Mutlak ölçütle** 4 saatlik açık ara önde: tek pozitif medyan Sharpe, hücrelerin
%38'i kârlı. **Al-tut'a göre** ise en kötüsü: 112 hücrenin sadece 22'si sade
al-tut'u geçiyor, medyan 55.8 puan geride.

Sebep tabloda görünüyor: 4 saatlik pencerede al-tut zaten **+%43** yapmış. O
pencerede pozitif getiri üretmek beceri gerektirmiyor; piyasada kalmak yetiyor,
ve kuralların çoğu piyasadan çıktığı için geride kalıyor. 15dk ve 1sa'te ise
al-tut −%19.5 ve −%45.9; orada "al-tut'u geçmek" büyük ölçüde **daha az maruz
kalmak** demek — alfa değil, düşük beta.

### Karşılaştırmanın yapısal kusuru: pencereler aynı değil

Her zaman dilimi ~8000 bar çekiyor, ama bu bar sayısı farklı takvim aralıklarına
denk geliyor:

| tf | medyan OOS bar | takvim karşılığı |
|---|---|---|
| 15dk | 8045 | ~84 gün |
| 30dk | 8128 | ~169 gün |
| 1sa | 8166 | ~340 gün |
| 4sa | 5628 | ~938 gün |

Yani "4 saatlik daha iyi" ile "4 saatliğin kapsadığı 2.5 yıl daha iyiydi" bu
düzenekte **ayrıştırılamaz**. Zaman dilimleri farklı rejimlerde ölçülüyor.
Temiz bir karşılaştırma dört dilimi de aynı takvim aralığına sabitlemeyi
gerektirirdi; bu koşuda yapılmadı, dolayısıyla yukarıdaki sıralama bir zaman
dilimi sıralaması değil, **zaman dilimi + pencere** sıralamasıdır. Deneyin
ilan edilen sorusuna ("hangi periyot kâr ettiriyor") verilebilecek dürüst cevap
budur: bu veriyle ayrıştırılamadı.

Strateji ailesi bazında da net bir kazanan yok — medyan Sharpe'lar macd +0.23'ten
bollinger_reversion −0.56'ya kadar sıralanıyor ve hiçbiri istatistiksel olarak
ayrışmıyor. long_flat (−0.35) ile long_short (−0.31) arasında da fark yok.

### Üç testin sonucu

Hiçbir hücre üçünü birden geçmiyor:

- **En yüksek turnuva-DSR 0.178** (eşik 0.95). 4352 denemenin maksimumu olarak
  deflate edildiğinde hiçbir Sharpe ayakta kalmıyor.
- **Bootstrap:** 284 hücreden **yalnızca 1'i** %5 seviyesinde anlamlı —
  `XRP/4sa/rsi_reversion/long_flat`, p=0.0167, OOS +%264 (al-tut +%129),
  Sharpe 1.33, 18 işlem. **Yerel** DSR'si 0.587 ile en yüksekler arasında, ama
  **turnuva DSR'si 0.0000**: tek başına bakıldığında etkileyici olan bu satır,
  4352 denemenin en iyisi olarak bakıldığında şans dağılımının içinde kalıyor.
  Deneyin özeti tek satırda budur.
- **PBO medyanı 0.575** (32 coin×tf bloğunun 19'unda >0.5). Örneklem-içi kazanan,
  örneklem dışında yarıdan fazla kez medyanın altına düşüyor. Tek istisna 4
  saatlik: medyan PBO 0.490 — sınırda, ama diğer üçünden belirgin şekilde düşük.

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

### İleri test sonucu — 6 gözlem, 4.7 saat

Defter altı long/short pozisyonla açıldı ve pencere boyunca onlarla kaldı:

| hücre | yön |
|---|---|
| XRP/15dk/rsi_reversion | SHORT |
| DOGE/30dk/rsi_reversion | LONG |
| TRX/1sa/sma_cross | SHORT |
| ETH/4sa/sma_cross | LONG |
| HYPE/30dk/tsmom | SHORT |
| SOL/30dk/rsi_reversion | SHORT |

| | |
|---|---|
| Farklı gözlem (mükerrer bar çıkarılmış) | **6** |
| Geçen süre | 4.7 saat |
| Başlangıç → bitiş | $10.000,00 → **$9.972,16** |
| Toplam getiri | **−%0,28** |
| Maksimum drawdown | −%0,35 |
| İşlem sayısı | 6 (hepsi ilk döngüde) |
| Ödenen maliyet | $15,00 |

Kayıp iki kabaca eşit parçadan oluşuyor: fiyat hareketinden **−$12,84** ve
açılışta bir kez ödenen **−$15,00** işlem maliyeti. Yani 4.7 saatlik sonucun
yarısından fazlası, ilk barda kitabı kurmanın bedeli.

**Bu pencere, sorulan soruyu test edemedi.** Kullanıcının istediği davranış —
her periyot sonunda analize göre yeniden short/long pozisyon açmak — hiç
tetiklenmedi: ilk döngüdeki 6 işlemden sonra **hiçbir sinyal dönmedi**, defter
4.7 saat boyunca statik kaldı. 15dk'lık bir kuralın 15dk'da bir işlem yapması
gerekmiyor (doğrusu da bu, `min_hold_bars`/`confirm_bars` tam olarak bunu
hedefliyor) ama sonuç olarak ileri test, bir yeniden-konumlanma stratejisini
değil, altı sabit pozisyonun 4.7 saatlik P&L'ini ölçtü.

**Örneklem büyüklüğü hakkında dürüstlük:** 6 gözlem, bir edge'i kanıtlamaya da
çürütmeye de yaklaşmaz. Bu ölçekte ortalama getirinin standart hatası, makul her
edge'i gölgede bırakır — −%0,28 ile +%0,28 arasında herhangi bir sonuç aynı
şeyi, yani hiçbir şeyi ifade ederdi. `paper.performance()` bunu gömmek yerine
`caveat` alanında açıkça söyler. Kağıt defter bir **kayıt**, kanıt değil.

## Nihai sonuç

Deney kapandı. Tek cümlelik cevap: **bu aramada, bu maliyetlerle, bu veride
konuşlandırmayı hak eden bir kural bulunamadı** — ve bulunamaması beklenen
sonuçtu.

Sayılarla:

- 4352 konfigürasyon backtest edildi, 2264'ü daha fitlenmeden maliyet taramasında
  elendi, 284 hücre değerlendirildi, **0 hücre üç testi birden geçti**.
- İleri kağıt defter 4.7 saatte 6 gözlemle **−%0,28** yaptı; bunun yarısından
  fazlası tek seferlik açılış maliyeti. Bu sayı hiçbir yöne kanıt değil.
- "Hangi periyot kâr ettiriyor" sorusu **cevaplanamadı**: zaman dilimleri farklı
  takvim pencerelerini kapsadığı için sıralama, periyodun kendisinden değil
  pencereden geliyor olabilir ve bu düzenek ikisini ayıramıyor.

Deneyin gerçek çıktısı sıralama değil, **düzeneğin kendisi**: sessizce yanlış
sonuç üreten iki hata (birim uyuşmazlığı yüzünden yapısal olarak 0 çıkan Deflated
Sharpe, ve ölü bir emir defterini +%8744'lük edge sanmak) ancak bu düzenek
kurulduğu için yakalandı. İkisi de exception atmadı, ikisi de makul bir sayı
üretti. Bir tanesi — DSR — dürüst bir null sonuçtan ayırt edilemeyen bir yanlış
negatif üretiyordu, ki bu mevcut en kötü hata biçimidir.

Kendi hipotezlerimden biri de bu süreçte çürütüldü: "liderlik tablosu koşudan
koşuya tamamen değişiyor, seçim gürültü" iddiası kontrollü testte 9/10 kesişimle
yanlış çıktı; kaynağı benim aradaki kod değişikliklerimdi.

Buradan devam edilecekse sıradaki adım daha fazla parametre taramak değil,
**karşılaştırmayı düzeltmek**: dört zaman dilimini de aynı takvim aralığına
sabitlemek, ve ileri testi sinyalin fiilen döndüğü kadar uzun bir pencerede
çalıştırmak.

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

Fiilen çalıştırılan koşu bu döngüyü kullanamadı: konteyner uyandırmalar arasında
askıya alındığı için ayrık bir arka plan döngüsü hayatta kalmıyor. Bunun yerine
her uyandırmada **senkron tek döngü** koşuldu, yani gerçekleşen kadans ~15dk
değil **~1 saat** oldu. 6 gözlemin 4.7 saate yayılmasının sebebi budur.

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
