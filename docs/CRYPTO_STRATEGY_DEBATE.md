# Panel tutanağı — «Kripto Piyasalarında Sistematik Strateji Arayışı: Negatif Sonucun Anatomisi»

*Deneysel bir münazara: `docs/CRYPTO_STRATEGY_EXPERIMENT.md`'deki deney, iki
karşıt uzman personası tarafından bağımsız olarak denetlendi. Her panelist
repoya, 44 serilik mum önbelleğine ve web araştırma araçlarına tam erişimle
çalıştı; her sayı ya arşiv dosyalarından okundu ya da panelistin kendi koştuğu
hesaptan geldi. Kural: tam 10'ar soru, sayı uydurmak yasak, doğrulanamayan şey
"doğrulanamadı" diye etiketlenir. İki tur: bağımsız bildiri + çapraz sorgu.*

*Bu bir simülasyondur; personalar kurgudur, veriler gerçektir. Hiçbir bölümü
yatırım tavsiyesi değildir.*

**Panelistler:**
- **Doç. Dr. Aylin Karahan** — iyimser/yapıcı taraf (multi-strateji fon ortağı personası). 1. turda 29 araç çağrısı, kendi bağımsız analizleri: dört kademeli maliyet duyarlılık taraması, 265 hücrelik sepet toplulaştırması, güç analizi, LINK reprodüksiyonu.
- **Prof. Dr. Kerem Aksoy** — kötümser/şüpheci taraf (piyasa mikroyapısı + backtest aşırı-uydurma literatürü personası). 1. turda 35 araç çağrısı: tur-3 kolunun birebir replikasyonu, slippage stres testi, embargo-deliği rejim analizi, null-dağılım simülasyonu, LINK'e bağımsız artefakt saldırıları.

**Moderatör:** deneyi yürüten sistem. Panelin deney hakkındaki maddi iddiaları
tutanak sonunda ayrıca doğrulanmıştır (§ Moderatör doğrulamaları).

---

## 1. TUR — Doç. Dr. Aylin Karahan (iyimser bildiri)

### AÇILIŞ

Bu deney 4.352 konfigürasyon denedi ve sıfır hayatta kalan buldu. Ben bu panele o sıfırı savunmaya gelmedim; o sıfırın **doğru sorulan bir sorunun doğru cevabı** olduğunu ve içinden üç ayrı, parası ödenmiş bilgi çıktığını göstermeye geldim.

Birincisi: sıfır, "kripto piyasalarında sistematik edge yoktur" demiyor. Deneyin fiilen test ettiği hipotez çok daha dardı: *perakende maliyetlerle (30bps gidiş-dönüş), tek enstrümanda, 15dk–4sa barlarda, 92 günlük tek bir ayı rejiminde, sekiz klasik teknik kuralla* edge var mı? Bu kümenin boş çıkması literatürün de öngördüğü sonuçtur: kısa vadede alfayı öldüren şey sinyal yokluğundan önce **turnover aritmetiğidir**. Deneyin en sağlam bulgusu da zaten kârlılığa hiç bakmayan bu aritmetik.

İkincisi: bu düzenek iki *sessiz* hatayı — yapısal olarak sıfır çıkan Deflated Sharpe'ı ve ölü emir defterinin ürettiği +%8744'lük sahte edge'i — yakaladı; p=0,002'lik bir "keşfi" üç bağımsız kontrolle infaz etti. Yanlış pozitif üretmeyen bir araç kadar, yanlış *negatifini* kendisi yakalayan bir araç da nadirdir.

Üçüncüsü: sonuç tablosu üç açık kapı bırakıyor — maliyet kademesi düştükçe canlanan 1sa/4sa hücreleri, tekil hücreler negatifken pozitife dönen portföy-seviyesi toplulaştırma ve 92 günün istatistiksel gücünün dışlayamadığı mütevazı edge bölgesi. "Kanıt yokluğu ≠ yokluk kanıtı" retoriğini nerede kullanmaya hakkım olduğunu sayılarla ayıracağım — çünkü iyimserliğin naif olanı, bu düzeneğin yakalamak için kurulduğu hatanın tam kendisidir.

### Karahan'ın 10 sorusu (bulgularıyla)

**S1 — Maliyet kademesi gevşetilirse fizibilite nasıl değişir?** 4.352 konfigürasyonun tamamı dört ücret seviyesinde yeniden tarandı. Fizibil konfigürasyon oranı: 30bps'te 15dk/30dk/1sa/4sa = %14/%31/%52/%91; 12bps'te %44/%72/%82/%99; 6bps'te %73/%90/%93/%100; 2bps'te %97/%100/%100/%100. Kritik düzeltme: brifingdeki "gereken brüt Sharpe 8,1/4,3/4,0/1,8" sayıları *tümü elenen hücrelerin* medyanıdır; ızgara-geneli medyan 1,85/0,88/0,55/0,11. → "15dk yapısal ölü" bir doğa yasası değil, **ücret kademesinin fonksiyonu**. Dürüst kayıt: fizibilite geçmek kâr etmek değildir.

**S2 — Maliyet düşünce seçilmiş konfigürasyonların net performansı değişiyor mu?** 265 liderlik satırının pozisyon patikaları sabit tutulup dört maliyet seviyesinde yeniden fiyatlandı: medyan Sharpe 15dk −0,54→+0,01; 1sa −0,28→+0,23; 4sa +0,46→+0,60 (30bps→2bps). *(Kendi dipnotu: deploy-parametre kontaminasyonu — seviyeler iyimser; seviyeler arası fark saf aritmetik. Bu dipnot 2. turda belirleyici oldu — bkz. çapraz sorgu.)* → Maliyet, hızlı dilimlerde kaybın yarısından fazlasını açıklıyor; ama sıfır maliyette bile parlak bir şey yok. Maliyet kanalı ile sinyal kanalı ayrıştı.

**S3 — 1sa'te 76/78'in al-tut'u geçmesi alfa mı, düşük beta mı?** Ölçüm: medyan maruziyet 0,47, long-oranı 0,42, medyan strateji maxDD −%22,3 vs al-tut −%38,2. → Dürüst teşhis: büyük ölçüde **düşük beta**. Ama "alfa değil" ≠ "değersiz": overlay/risk-hedefleme katmanı olarak ürün olabilir. *(2. turda bu iddia null simülasyonuna yenildi ve geri çekildi.)*

**S4 — Düzenek kaç yanlış pozitifi önledi?** 265 hücrede: 63 hücre naif süreçte "konuşlandırılabilir" görünürdü (pozitif OOS + al-tut'u geçen); 30 hücre Sharpe>1; 10 hücre Sharpe>2; 2 hücre p<0,05. Üçlü kapı hepsini kesti, gerekçeler satır satır kayıtlı. → Negatif sonuç satın alınmış sigortadır.

**S5 — 92 günün istatistiksel gücü neyi dışlayabilir?** SE(yıllık Sharpe) ≈ 2,0. Tek yanlı %5 tespit eşiği: gözlenen Sharpe ≥ 3,28. Gerçek SR=1,0 için güç %11; %80 güç ~9,3 yıl ister. → Deney SR≤1,5–2 bandındaki hiçbir gerçek edge'i dışlayamadı; "kripto intraday'de edge yoktur" bu veriden çıkarılamaz. Ama medyanların dört dilimde negatif olması, "belki vardı da göremedik"in teselli değeri olmadığını söylüyor. Bu bir tarama+eleme deneyiydi ve işlevini gördü.

**S6 — Histerezis (confirm_bars) genellenebilir ilke mi, maliyet artefaktı mı?** Eşleştirilmiş 336'şar çiftte medyan ΔSharpe (band lehine): 15dk +0,47 @30bps ama +0,16 @6bps; 4sa'te aleyhte. → Histerezis bir **maliyet-savunma mekanizmasıdır**, alfa kaynağı değil. "15dk meşru bir örnekleme frekansı, gayrimeşru bir işlem frekansıdır" ilkesi hem bu veride hem literatürde (Bysik & Ślepaczuk, doğrulandı) ayakta.

**S7 — LINK vakası kayıp mı, değerli çıktı mı?** Bağımsız reprodüksiyon: LINK +%126,3 (pencere farkıyla; arşiv +%123,41), diğer yedi coin 6/7 uyumla kaybediyor; lag-1 AC −0,021 (ortalamaya dönüşü en zayıf 2. seri). → İnfaz doğruydu. {tek-vuruş → kesit → mekanizma} üçlüsü her keşif iddiasına uygulanabilir bir **öldürme protokolü**; LINK ise kayıt-öncesi tek hipotez olarak ucuza yeniden test edilebilir.

**S8 — Sonuç "stratejiler çalışmıyor" mu, "ayıda çalışmıyor" mu?** OOS penceresinde 8/8 coin negatif (al-tut medyan −%22,1; Sharpe'lar −0,48…−2,75). → Hizalı sonuç tek rejimin sonucudur; "hiçbir rejimde çalışmaz" çıkarılamaz. Kalıcı bulgu dilim sıralaması değil, **maliyet gradyanı + rejim bağımlılığı**. Çok-rejimli tekrar bu altyapıda ucuz.

**S9 — Portföy-seviyesi toplulaştırma ne yapıyor?** 265 hücrenin OOS serileri dilim başına eşit-ağırlık sepette: korelasyon 0,12–0,31; 1sa sepeti +0,27, 4sa sepeti **+2,07** (tekil medyan +0,46 iken). *(Kendi uyarısı: kontaminasyon + tek rejim + deflasyonsuz — "kanıt değil, ölçülmüş hipotez". 2. turda bu satır rakibin kontaminasyon ölçümüyle düştü.)* → Değerlendirme birimi hücre değil sepet olmalı.

**S10 — İleri defter uzatılırsa ne öğrenilir?** Ölçülen kadans ~10–12 işlem/hafta → 8–12 haftalık pencere yeniden-konumlanma mantığını onlarca kez tetikler; edge kanıtı ise hiçbir makul sürede mümkün değil (12 haftada SE hâlâ ±2,1). → Kağıt defter **operasyonel doğrulama aracıdır**; ondan kanıt istemek kategori hatası.

### Karahan'ın 1. tur kapanışı (özet)

Hiçbir tekil hücreye — LINK dahil — sermaye yok; sıfır hayatta kalan hükmü bu evren ve maliyetler için doğrudur. Ama düzenek **maliyet kalemi değil, varlıktır**: dışarıdan gelecek her strateji teklifinin önüne konacak bir eleme makinesi. İkinci faz üç değişiklikle fonlanmalı: birim sepete taşınsın, maliyet erişilebilir kademeye insin, OOS çok-rejimli bir yıla uzasın. Yapılmaması gereken tek şey: bu negatif sonucu "kripto sistematik strateji taşımaz" genellemesine çevirmek.

---

## 1. TUR — Prof. Dr. Kerem Aksoy (kötümser bildiri)

### AÇILIŞ

Yirmi beş yılda iki fon batışına içeriden tanık oldum; ikisinde de duvarda asılı olan şey güzel bir backtest'ti. Önce hakkı teslim edeyim: bu deney, alanda gördüğüm bireysel çalışmaların çoğundan daha disiplinli. Sessiz hataları deneyci kendisi yakalamış; null sonucu manşet yapmış; ve benim bağımsız saldırılarımın bir kısmı da **başarısız oldu** — bunu raporlamak şüpheciliğin namusudur. LINK satırını birebir yeniden ürettim, bir bar ekstra icra gecikmesiyle öldürmeye çalıştım, ölmedi (+%125,5); bootstrap blok uzunluğunu 20→2000 bar taradım, p 0,002'de sabit kaldı; liderlik kararlılığını (9/10) doğruladım.

Ama teslimiyet burada biter. Bu düzeneğin cevaplayabildiği soru ile cevapladığını iddia ettiği soru aynı değil. Üç turda üç kez değişen metodolojinin hizalı kolu 0,2–0,8 Sharpe oynuyor; benim dördüncü tur pertürbasyonlarımda 4 saatlik kol bazı makul seçimlerde **tamamen ölçülemez** hâle geliyor. "Dört dilimde birebir aynı OOS penceresi" ikinci derecede çöküyor: embargo delikleri sıçrama günlerine denk gelmiş. 92 günlük tek ayı rejimi, 4sa'te hücre başına ~4 bağımsız epizot demek. Maliyet tarafında 5bps slippage ve funding=0, kısa-ağırlıklı bir kitap için bu rejimde belgelenebilir şekilde iyimser.

### Aksoy'un 10 sorusu (bulgularıyla)

**S1 — Üç tur metodoloji değişikliği: forking paths mi?** Kendi "tur 4" pertürbasyonu koşuldu (n_folds∈{4,5,6}, embargo∈{24,48}): 1sa medyanı −0,76…−1,09 bandında; fold=4 veya embargo=48'de **4sa kolu tamamen değerlendirilemiyor (0/113)**. → Her tur commit'li ve A/B'li — bahçenin en dürüst gezilme şekli; ama dilim *sıralaması* bu düzenekten çıkarılamaz. Gürbüz tek önerme: "hiçbir dilimin medyanı pozitif değil" — her varyantta ayakta.

**S2 — Embargo delikleri benchmark'ı kaydırıyor mu?** Fold düzeni yeniden kuruldu: SOL/1sa'nin dört deliği +2,11/+1,39/+10,24/+3,31'lik günleri yutmuş; ölçülen benchmark −%27,56 vs pencerenin gerçeği −%14,49 — **13 puan fark**. → "OOS penceresi birebir aynı" bar-düzeyinde doğru, getiri-düzeyinde yanlış. Sıralama identifiye edilemez.

**S3 — "Al-tut'u geçen" metriğinin null'u ne?** Ölçülen tutma süresine kalibre 4.000'er rastgele kitap simüle edildi: long/flat'lerin **%78,1'i**, long/short'ların %74,4'ü al-tut'u geçiyor. → Null yerden bitme; metriğin mekanizması alfa değil maruz kalma azaltımı. Komite bu sütunu yok saymalı.

**S4 — 5bps slippage: 15bps'te ne kalıyor?** Tur-3 kolu birebir replike edildi (rapora tıpatıp), sonra 50bps GT'de: medyan Sharpe −1,20→−1,37 / −1,33→−1,89 / −0,94→−1,57 / −0,80→−0,89. Kapıdan geçen kirli seriler: ADA/30dk stale %17,6, AVAX/1sa %14,3 — hepsi eşiğin hemen altında, hepsi Binance.US. → Negatif sonuç maliyetle güçlenir; ama fizibilite tablosu 5bps'e çıpalıyken "yapısal pozitif" diye satılamaz. 4sa maliyet duyarlılığında en dayanıklı kol — yine de negatif.

**S5 — LINK infazı doğru gerekçeyle mi?** İki bağımsız artefakt saldırısı: 2-bar gecikme → +%125,53 (bounce hipotezi çürüdü); 15/25bps → +%111/+%100 (maliyet de öldürmüyor). Bootstrap p blok seçimine duyarsız. LINK OOS lag-1 AC −0,0091 ≈ rastgele yürüyüş; Bonferroni eşiği 1,9×10⁻⁴, p=0,002 geçemiyor; 265 satırda p<0,05 sayısı 2 (bağımsızlık beklentisi ~13). → **Deney burada sağlam:** kalan tek açıklama deneyinkiyle aynı — çoklu-test şansı. Üç-otopsi refleksi kopyalanmalı.

**S6 — funding=0 ve spot-mum/perp-icra uyumsuzluğu?** Dönem kaynakları: 2026 başından beri kalıcı negatif funding (BTC −%0,0090/8sa; alt'lar zamanın ~%40'ı negatif). Negatif funding = **short öder**: hep-short bacak 92 günde ~%2,76, stresle epizodik %8–14. Kağıt defter 4 short / 2 long açıldı; motor 0 funding yazdı. → Medyanın işaretini değiştirmez; ama long/short vitrini ve kısa-ağırlıklı ileri kitap **sistematik iyimser**. Bu pencerede yön belli: aleyhte.

**S7 — 4.352 deneme gerçekte kaç deneme?** Korelasyon matrisinden etkin bağımsız sayı: 4sa 113 hücre → **8,6**; 15dk 25 → 5,7. PBO replikasyonu 0,6488. → DSR nominal M ile aşırı-deflate ediyor (Harvey-Liu etkin-N düzeltmesi yok); bootstrap aile-genelini görmüyor; bilgilendirici tek test PBO ve cevabı net: seçim gürültü. *(2. turda "sıfır tasarıma gömülü" iması, rakibin M-süpürmesiyle nicel olarak çürütüldü ve geri çekildi.)*

**S8 — İleri defter kimin kazananlarını test etti?** Zaman damgaları çakıştırıldı: defter 08-01 04:09'da kuruldu — hizalama commit'inden (10:46) önce; seçen turnuva eski evrenli (TRX/HYPE/BNB) run-4; altı slotun altısı `selected_without_significance: true`. → "6 gözlem kanıt değildir" dürüst; eksik itiraf: defter **nihai metodolojinin hiçbir ürününü** test etmiyor. İleri testin kanıt değeri sıfır değil, *tanımsız*.

**S9 — A/B kolları aynı veriyi mi gördü?** Kod okuması + log karşılaştırması: `merged = cached_rows + fresh` borsalar-arası dikişe izin veriyor; tur-3'te hizalı kol AVAX/30dk'yı Binance.US'ten alıp reddetti, hizasız kol aynı seriyi OKX'ten alıp değerlendirdi — **iki kol farklı veri gördü**; replikasyon 30dk'da 49 değil 55 hücre buluyor. Ayrıca doküman-arşiv sayım uyuşmazlığı: "284'te 1 anlamlı" vs run4'te 2. *(Moderatör doğrulaması: bkz. § Moderatör doğrulamaları — anlık görüntü karışıklığı, ama içindeki ders gerçek.)* → Hiçbiri sonucu deviren hata değil; ama "kontrollü A/B"nin kontrolü cache mutasyonuyla deliniyor. Hakem notu: "veri katmanını dondur, yeniden koş."

**S10 — 92 günden ne genellenebilir?** Bysik & Ślepaczuk künyesi doğrulandı; aktarılmayan nüans: aynı makalede kazanan cost-aware strateji bile Holm-düzeltmeli bootstrap'ta al-tut'a üstünlüğü reddettiremiyor — "filtre turnover'ı kurtarır, alfa iddiasını kurtarmaz." → Genellenebilir olan yalnız maliyet aritmetiği ve turnover disiplini. Sonraki ayıda short kitapların, boğada trend kitaplarının davranışı hakkında bu pencere **hiçbir şey** söylemez.

### Aksoy'un 1. tur kapanışı (özet)

Hiçbir hücreye, hiçbir kaldıraçla sermaye yok — deneyin kendi hükmü de bu ve replikasyonlarımda sağlam. Altyapı fonlanmaya değer — strateji değil, filtre olarak. Devam şartları: dondurulmuş veri katmanı; 2020–2026, en az üç rejim; slippage 5/15/30bps zorunlu üçlü rapor; sızıntısız purge tasarımı; DSR yerine etkin-N'li aile testi (SPA/StepM), PBO ana metrik; nihai metodolojinin kendi kazananlarıyla haftalar süren ileri defter. Bunlar bitene dek dosyanın rafı: "değerli negatif sonuç; yatırım tezi yok."

---

## 2. TUR — Çapraz sorgu

### Karahan'ın tavizleri (3)

1. **"Al-tut'u geçen" iddiası geri çekildi.** Rakibin %78'lik null bulgusu bağımsız simülasyonla doğrulandı (kendi ölçümü: %74,9/%70,2; DOGE'de %94'e kadar). "Doğrulanmış risk-azaltım motoru" iddiası düştü; kalan tanımlayıcı istatistiklerin kural setine özgü olduğu gösterilemiyor. Overlay fikri ancak rastgele-kitap null'una karşı fazladan değer kanıtlarsa geri gelir.
2. **Funding'in yönü belli ve aleyhte.** "Yönü bilinmez" cümlesi geri çekildi; maliyet-gevşetme tablosunun long_short satırlarına yıldız kondu — funding netlenmeden karar girdisi yapılamaz.
3. **İleri defter provenance'ı.** Dosya okumasıyla doğrulandı (TRX/HYPE'lı eski evren, `selected_without_significance: true`); "uzat" tavsiyesi "nihai metodolojiyle sıfırdan kur"a dönüştü.

### Karahan'ın karşı saldırıları (3)

1. **Maliyet suçlaması simetrik.** Rakibin "kirli seri" listesindeki dört seri de Binance.US — aynı coinler OKX'te %1–2 stale; bu bir maliyet-tabanı kanıtı değil, düzeneğin zaten çözdüğü venue kusuru. Rakibin kendi alıntıladığı literatür 10bps GT'yi "ihtiyatlı" sayıyor; 50bps taban majörlerde savunulamaz. Ve rakibin kendi stres testinde 4sa yalnız −0,80→−0,89 kaydı: **maliyet tartışması hangi yönde çözülürse çözülsün 4sa kapısına dokunmuyor.**
2. **Etkin-N bulgusu sepeti çürütmüyor, üretiyor.** Yeni hesap: 4sa korelasyon matrisi → ortalama rho 0,076, N_eff 11,8 (rakibin 8,6'sıyla aynı mertebe); aynı matristen sepet Sharpe +2,03, korelasyon-öngörülü +0,96. Aynı rho iki sonucu birden doğuruyor: deneme sayısı nominalden küçük *ve* çeşitlendirme kazancı gerçek. *(Bu satır rakibin kontaminasyon ölçümüyle 2. turda sınırlandı — bkz. Aksoy karşı saldırı 1.)*
3. **"Sıfır tasarıma gömülü" nicel olarak yanlış.** M-süpürmesi: LINK'in turnuva-DSR'si M=4352→0,19; M=265→0,43; M=25→0,72; **M=8,6→0,85**. En cömert düzeltmede bile 0,95 eşiği geçilmiyor; sıfır, deflasyon kalibrasyonunun artefaktı değil. Eşiği tutan şey M değil, 92 günlük örneklem + kurtosis 17,8.

### Aksoy'un tavizleri (3)

1. **"15dk yapısal ölü" hükmü daraltıldı.** Rakibin 30bps satırı bağımsız doğrulandı; brifing düzeltmesi (8,1 = en kötü hücrelerin medyanı) haklı. Yeni cümle: "15dk, perakende taker maliyetinde ölü; düşük kademede jüri dışarıda" — ama o dünyaya funding'siz girilmez (karşı saldırı 3).
2. **Güç analizi ortak mühimmat ilan edildi.** "Keşfedememek tasarıma gömülü" imasının suçlayıcı tonu geri çekildi: **bu düzenek mikroskop değil, elektir** — ve elek olarak işini görmüş.
3. **Düşük-beta overlay'i ürün hipotezi olarak kabul.** Şartla: kıyas çıtası al-tut değil, *sabit 0,47 maruziyet* ve basit vol-hedefleme olmalı — rastgele-kitap bulgusu mekanizmanın beceri gerektirmediğini gösteriyor.

### Aksoy'un karşı saldırıları (3)

1. **Deploy-parametre kontaminasyonu ölçüldü — sepet ve maliyet-merdiveni pozitifleri onun üstünde duruyor.** Repriced-seviye ile gerçek walk-forward medyanı arasındaki fark: **15dk +0,27, 30dk +0,49, 1sa +1,01, 4sa +0,93 Sharpe.** Rakibin "1sa maliyet düşünce pozitife dönüyor" işaret değişimi tam bu bandın içinde (repriced +0,01 vs gerçek WF −1,01). Gerçek fold-seçimli OOS serileriyle eşit-ağırlık sepetler **negatif**: 15dk −1,94, 30dk −1,73, 1sa −1,50, 4sa **−4,03**; üstelik 1sa sepeti (−1,50) medyan tekil hücreden (−0,94) kötü — negatif ortalamalı korelasyonlu serilerde volatilite düşerken kayıp kalır. **"Sepet +2,07" bu veride yoktur; kontamine bir gölgedir.**
2. **Sepet, rakibin kendi güç duvarına çarpıyor.** Nominal +2,07 bile 76 günlük pencerede SE≈2,2–2,8 ile sıfırdan bir standart hatanın altında. Korelasyon okumaları çelişmiyor: ortalama rho 0,12 *ve* N_eff 8,6 — düşük ortalamanın altında güçlü ortak faktör; çeşitlendirme 1/√113 değil 1/√9 ile sınırlı. Sepet ayrıca aramanın *çıktısı* üzerine sonradan seçilmiş bir birimdir — kendi deflasyonundan geçmeli, geçemez.
3. **Ucuz-maliyet dünyası perp dünyasıdır ve funding=0 yoktur.** 2–6bps icra ancak perp'te var; 4sa'te ortalama tutma 20,1 gün × ~3bp/gün funding → **pozisyon-epizodu başına ~60bps** — "12bps taban perp taker" varsayımının beş katı. Ücret düştükçe bağlayıcı sürtünme funding'e devrolur ve en çok, en uzun tutan 4sa kolunu vurur. 2bps "maker icra" satırı dolum riskini sıfır sayar: momentum girişleri tam fiyat kaçarken emir ister, maker dolumları ters-seçilimlidir. **Merdivenin üst basamağı gerçek, alt basamakları bu kural aileleri için model değil, dilek.**

Ayrıca kayıt disiplini notu: rakibin "+%126,3 reprodüksiyonu" arşivdeki satır değildir (arşiv +%123,41; kendi replikasyonu bit-düzeyinde tutuyor) — kayıt disiplinini savunan bir bildiride yeniden-üretim arşivle eşleşmelidir.

### Nihai pozisyonlar

**Karahan:** Üç şey değişti — al-tut sütunu kanıt listesinden çıktı; long_short maliyet satırları funding netlenene dek askıda; ileri defter tavsiyesi "yeniden kur"a döndü. Değişmeyenler daha önemli: maliyet aritmetiği iki tarafın stres testlerinde de ayakta; 4sa kapısı rakibin 50bps kolunda bile kapanmadı; sepet bulgusu ile etkin-N bulgusu aynı ölçümün iki yüzü çıktı ve birlikte bir sonraki deneyin tasarımını yazıyor. "Sıfır hayatta kalan", LINK'in M=8,6'da dahi 0,85'te kalmasıyla, artık iki panelistin *bağımsız yöntemlerle* vardığı ortak sonuçtur. Fark artık sonuçta değil: bu dosya rafa mı kalkar, yoksa bir sonraki deneyin şartnamesi midir — ben ikincisini savunuyorum ve şartnamenin yarısını bu çapraz sorgu yazdı.

**Aksoy:** Üç şey değişti — "15dk yapısal ölü" maliyet-kademesine koşullu hâle geldi; güç eleştirisi suçlama olmaktan çıkıp ortak çerçeve oldu; düşük-beta katmanı ölçülebilir ürün hipotezi olarak kabul edildi. Değişmeyenler: hiçbir hücreye ve hiçbir sepete sermaye yok — çünkü rakibin iki "açık kapısından" biri +0,5…+1,0 Sharpe'lık kontaminasyonun üzerinde duruyor ve gerçek serilerle dört sepetin dördü negatif; öteki, funding'i sıfır sayan bir dünyada fiyatlanmış. Karahan ile aynı makineye bakıyoruz ve ikimiz de ona sermaye değil, veri verilmesini istiyoruz; farkımız şu — o makinenin kapılarını açık tutuyor, ben açık kalmış kapıların hangi rüzgârla çarptığını ölçüyorum. Sıfır hayatta kalan hükmü her iki okumada da ayakta.

---

## MODERATÖR DOĞRULAMALARI

Panelin deney hakkındaki maddi iddiaları arşive karşı kontrol edildi:

1. **"Doküman '284'te 1 anlamlı' diyor, arşivde 2 var" (Aksoy S9e):** Kısmen anlık-görüntü karışıklığı. `tournament_run4.json` (10:25'teki koşu-4 arşivi) gerçekten 2 anlamlı hücre içeriyor: XRP/4sa p=0,0167 **ve** TRX/4sa p=0,0053 (+%190 OOS — al-tutun +%359'unun altında). Dokümandaki "yalnızca 1" cümlesi ise 28 dakika sonraki nihai koşu-5 için yazılmıştı ve o koşu için doğruydu. **İçindeki gerçek ders:** TRX/4sa'nin p-değeri iki koşu arasında 0,0053'ten anlamsıza kaydı — bootstrap anlamlılığının veri tazelenmesine karşı kırılganlığı, tek-koşu p-değerlerine güvenilmemesi gerektiğinin bir başka kanıtı.
2. **"A/B kolları AVAX/30dk'da farklı borsa verisi gördü" (Aksoy S9b):** Doğru ve gerçek bir kusur. Kalite kapısı venue seçimini koşu anında yapıyor; iki kol arasında cache tazelenince seçim değişebiliyor. "Veri katmanını dondur" şartı kabul edildi.
3. **Karahan'ın "+%126,3" reprodüksiyonu (Aksoy'un kayıt notu):** Doğru tespit — Karahan pencereyi birebir arşiv penceresiyle değil kendi kurduğu pencereyle koştu; işaretler ve mertebe tutuyor, rakam tutmuyor. Tutanağa "pencere farkı" şerhiyle geçirildi.
4. **Kontaminasyon ölçümü (Aksoy karşı saldırı 1):** Yöntem doğru — `tournament_latest.json` OOS serilerini saklamaz, dolayısıyla Karahan'ın repricing'i zorunlu olarak deploy-parametreli tam-pencere yeniden inşasıydı. "Her hücrenin walk-forward OOS serisi arşivlensin" şartı motora eklenmesi gereken bir eksiklik olarak kabul edildi.

## ORTAK SONUÇ BİLDİRGESİ (her iki panelistin metinlerinden derlendi)

**Mutabakat — sermaye:**
- Bu deneyin hiçbir hücresine, hiçbir sepetine, hiçbir kaldıraç seviyesinde sermaye tahsis edilmez.
- "Sıfır hayatta kalan" hükmü iki bağımsız denetimde de ayakta; en cömert etkin-deneme düzeltmesinde bile (M=8,6) en güçlü satır DSR 0,85 < 0,95.

**Mutabakat — bilgi:**
- En sağlam yapısal bulgu maliyet aritmetiğidir ve iki tarafın stres testlerinde de ayakta kalmıştır; ancak tek sayı değil, kademe+funding+dolum-riskiyle birlikte bir *eğri* olarak raporlanmalıdır.
- Bu düzenek bir mikroskop değil, elektir (SE(Sharpe)≈2,0 @ 92 gün): SR≤2 bandındaki edge'leri ne bulabilir ne dışlayabilir. Elek olarak işini görmüştür: naif süreçte pazarlanabilir 10–63 aday kesilmiştir.
- Dilimler arası sıralama bu veriden identifiye edilemez; gürbüz tek önerme "hiçbir dilimin medyanı pozitif değil"dir.
- "Al-tut'u geçen" sütunu yaklaşık bilgisizdir (null %74–78) ve karar girdisi olamaz.
- Histerezis maliyet-savunma mekanizmasıdır, alfa kaynağı değil.

**Kayıtlı ihtilaflar (çözülmedi):**
- Maliyet merdiveninin alt basamaklarının (2–6bps) bu kural aileleri için *modellenebilir* olup olmadığı (Karahan: eğrinin ucu; Aksoy: funding'siz dilek).
- Sepet biriminin vaadi (Karahan: N_eff'le birlikte sonraki deneyin tasarım hipotezi; Aksoy: gerçek serilerle negatif, kayıt-öncesi ilan şart).
- Dosyanın rafı: arşiv mi, şartname mi.

**Ortak şartname (bir sonraki deney için, iki listenin birleşimi):**
1. Veri katmanı dondurulmuş, tek-venue, borsalar-arası dikiş yasak; perp mumları + gerçek funding serileri.
2. Her hücrenin walk-forward OOS serisi arşivlensin (sepetler ancak öyle dürüst değerlendirilir).
3. 2020–2026, en az üç rejim penceresi (ayı + boğa + yatay).
4. Slippage sabit değil: 5/15/30bps zorunlu üçlü rapor; maliyet hücre-başına girdi.
5. Embargo deliklerinin rejim-yükü ölçülsün; sızıntısız, takvim-eşit purge tasarımı.
6. DSR yanına etkin-deneme-düzeltmeli aile testi (SPA/StepM); PBO ana metrik.
7. Sepet birimi ve "neden LINK" hipotezi **kayıt-öncesi** ilan edilsin.
8. İleri defter nihai metodolojinin kendi kazananlarıyla sıfırdan, 8–12 hafta; rolü operasyonel doğrulama, kanıt değil.
9. Overlay iddiaları al-tut'a değil, sabit-maruziyet ve vol-hedefleme çıtasına karşı test edilsin.

---

*Tutanak, iki subagent'in tam metinlerinden derlenmiştir; 1. tur bildirileri
bulgu özetleriyle, 2. tur metinleri neredeyse eksiksiz aktarılmıştır. Panelin
deney üzerinde bulduğu kusurlar (§ Moderatör doğrulamaları) ana deney
dokümanına da işlenmiştir. Hackathon prototipi — hiçbir çıktı yatırım
tavsiyesi değildir.*
