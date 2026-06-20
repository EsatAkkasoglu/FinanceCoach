# Ürün Odağı — "Az ama Öz" Planı

> Amaç: FinCoach'u "her şeyi yapan" bir İsviçre çakısından, **tek bir tekrar eden
> değer döngüsünü** mükemmel yapan bir neştere çevirmek. Bu doküman hangi
> özelliğin kalacağını, hangisinin gizleneceğini/kesileceğini ve neden olduğunu
> tek sayfada gösterir.

## Çapa (anchor)

**Hedef kişi (ICP):** 28–40 yaş, beyaz yaka, TEFAS/BIST'te birikim yapan ama
"hangi fonu alayım, param eridi mi, şimdi ne yapmalıyım" diye sürekli kaygılanan,
finansal okuryazarlığı orta seviye Türk bireysel yatırımcı.

**Çözülen iş (job-to-be-done):** *"Finansal kaygımı azalt ve bir sonraki adımı
benim için netleştir."* — veri göstermek değil, **karar/kaygı yükünü azaltmak.**

**Wedge (farklılaşma):** TEFAS + BIST + kripto'yu **Türkçe konuşan bir AI** ile
birleştirmek. ChatGPT TEFAS'ı/`.IS` hisselerini bilmez; yabancı fintech'ler
Türkiye'yi umursamaz. Boşluk burada.

## Kahraman döngü (hero loop) — tek odak buraya

Tüm ürün bu **tekrar eden** döngüyü beslemeli; beslemiyorsa v1'de yok:

```
Onboarding (kısa)  →  Portföy/Fon takibi (TEFAS/BIST/kripto)
        →  Haftalık özet + PROAKTİF haber uyarısı
        →  "Koça sor" (bağlamlı AI)  →  kullanıcı geri döner
```

Neden bu döngü: tek seferlik "vay be" değil, **geri getiren kanca** var
(proaktif uyarı + haftalık özet). Para veren özellik budur.

## Özellik triyajı

| Özellik | Tekrar eden işi besliyor mu? | Karar |
|---|---|---|
| Onboarding (hedef, risk, portföy) | Evet — döngünün girişi | **TUT** (ama tek ekrana indir, aşağıya bak) |
| Portföy takibi (hisse/kripto, canlı fiyat) | Evet — döngünün kalbi | **TUT** |
| Fon analizi / TEFAS keşif | Evet — wedge'in çekirdeği | **TUT** |
| Proaktif haber uyarıları + "koça sor" | Evet — retention motoru | **TUT (öne çıkar)** |
| Haftalık/aylık özet (briefing) | Evet — geri getirir | **TUT (öne çıkar)** |
| Net worth genel görünüm | Kısmen — "neden"i verir | **TUT (ikincil)** |
| Hedef planlama (goals) | Kısmen — motivasyon | **TUT (ikincil)** |
| Bütçe / işlem / abonelik / hesap takibi | Hayır — **ayrı bir ürün** (Mint tarzı) | **GİZLE** — wedge'i sulandırıyor, bakımı pahalı |
| Doküman çıkarımı (ekstre/bordro OCR) | Hayır — tek seferlik, sürtünmeli, hata riskli | **GİZLE** — "vay be" ama job değil |
| Kripto türev araçları (funding/liq.) | Hayır — niş + regülasyon riski | **GİZLE** |
| Sesli özet (audio overview) | Hayır — nice-to-have | **GİZLE** |

> "Gizle" = silme; feature-flag arkasına al, menüden çıkar. Kod kalır, **bilişsel
> yük** kalkar. Kullanıcı 5 şey görünce 1'ini anlar; 12 şey görünce 0'ını.

## Onboarding'i tek ekrana indir

Şu an onboarding 7 alan topluyor (isim, avatar, hedef, tutar, tarih, gelir,
hesaplar, risk, portföy). Bu, kullanıcının değeri görmeden önce çok fazla iş.
**v1 minimum:** (1) tek finansal hedef, (2) risk profili (hızlı 3 soru), (3)
portföy/izleme listesi (1–2 sembol/fon). Gerisini ilk değer anından *sonra* iste.

## "Yapılamıyor / anlaşılmıyor" sorununa cevap

Senin "özellikler çok ama yapılabilmesi mümkün değil, kullanıcı nasıl yapacağını
anlamıyor" tespitin bir **scope + onboarding** sorunudur, yetenek sorunu değil.
Çözüm: yüzeyi küçült (yukarıdaki triyaj) + her ekranda **tek net sonraki aksiyon**
("Şimdi ne yapmalıyım?" → koça sor) bırak.

## Başarı ölçütü (v1)

- Aktivasyon: onboarding'i bitirip ilk koç cevabını gören kullanıcı oranı.
- Retention: 1 hafta sonra proaktif uyarıya tıklayıp geri dönen kullanıcı oranı.
- Bu iki sayı yükseliyorsa wedge tutuyor; yükselmiyorsa job yanlış — pivot.
