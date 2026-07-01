/**
 * Bilingual legal content (EN + TR) for FinCoach.
 *
 * Long-form prose lives here (not in i18n JSON) so the two languages sit side
 * by side and parity is auditable. These are DRAFT templates reflecting the
 * app's real data practices — they are NOT legal advice and MUST be reviewed by
 * a qualified lawyer (and the data-controller details filled in) before any
 * public launch. Placeholders in [BRACKETS] need the operator's real values.
 */
import type { SupportedLanguage } from "@/lib/routing";

export type LegalSlug = "privacy" | "terms" | "disclaimer" | "refund";

export interface LegalSection {
  heading: string;
  /** Paragraphs; rendered with spacing. Use "- " prefix for list items. */
  body: string[];
}

export interface LegalDoc {
  title: string;
  updated: string;
  /** Shown in a warning banner — this is a draft, not legal advice. */
  draftNote: string;
  sections: LegalSection[];
}

// Operator-specific values — REPLACE before launch.
const COMPANY = "FinCoach";
const CONTACT_EMAIL = "hello@fincoach.app";
const EFFECTIVE = "26.06.2026";

type Bundle = Record<LegalSlug, LegalDoc>;

const EN: Bundle = {
  disclaimer: {
    title: "Disclaimer — Not Investment Advice",
    updated: `Last updated: ${EFFECTIVE}`,
    draftNote:
      "Draft template — informational only, not legal advice. Have a lawyer review before launch.",
    sections: [
      {
        heading: "Educational use only",
        body: [
          `${COMPANY} is an educational and informational tool to help you understand and organize your personal finances. It is not licensed investment advisory under the Turkish Capital Markets Board (SPK) or any other regulator, and nothing it produces is a personalized investment recommendation.`,
          "We do not tell you to buy, sell, or hold any security, fund, or crypto asset. Any figures, summaries, or scenarios are illustrative.",
        ],
      },
      {
        heading: "AI can be wrong",
        body: [
          "Responses are generated with the help of large language models and live third-party market/news data. They can be incomplete, out of date, or simply incorrect. Always verify independently before making a financial decision.",
        ],
      },
      {
        heading: "Markets carry risk",
        body: [
          "All investing involves risk, including loss of principal. Past performance does not guarantee future results. You are solely responsible for your own decisions and their outcomes.",
        ],
      },
      {
        heading: "No liability",
        body: [
          `To the maximum extent permitted by law, ${COMPANY} and its operator accept no liability for any loss arising from reliance on the service. For decisions with real financial consequences, consult a licensed professional.`,
        ],
      },
    ],
  },
  privacy: {
    title: "Privacy Policy & KVKK Notice",
    updated: `Last updated: ${EFFECTIVE}`,
    draftNote:
      "Draft template — fill in the data-controller (trade name, address, VERBİS) and have a lawyer review before launch.",
    sections: [
      {
        heading: "Data controller",
        body: [
          `The data controller is [REGISTERED TRADE NAME / SOLE PROPRIETOR], [ADDRESS], [VERBİS NO IF APPLICABLE]. For any privacy request, contact ${CONTACT_EMAIL}.`,
        ],
      },
      {
        heading: "What we collect",
        body: [
          "- Account & identity: email and/or username, authentication identifiers (via Firebase Authentication).",
          "- Profile: display name, monthly income, risk score and profile, avatar.",
          "- Financial data you enter or import: holdings, transactions, accounts and balances, goals, subscriptions, watchlist.",
          "- Uploaded documents: bank statements, receipts and similar files, plus the text extracted from them.",
          "- Conversations: your chat messages with the AI coach and their history.",
          "- Technical: basic logs needed to operate and secure the service.",
        ],
      },
      {
        heading: "Why we process it (purposes & legal basis)",
        body: [
          "We process this data to provide the service, generate AI responses, and personalize your experience — based on performance of our contract with you (KVKK Art. 5/2-c) and, where required (e.g. cross-border AI processing), your explicit consent (KVKK Art. 5/1).",
        ],
      },
      {
        heading: "Processors & cross-border transfer",
        body: [
          "To generate responses, the content of your messages and the text of uploaded documents is sent to Google's Gemini API for processing. Authentication uses Google Firebase, and hosting uses Google Cloud. This involves transfer of data to servers that may be located outside Türkiye (KVKK Art. 9).",
          "Live market and news providers (e.g. yfinance, NewsAPI, TEFAS, SEC EDGAR) receive only your queries (such as a ticker), not your personal financial records.",
        ],
      },
      {
        heading: "Retention",
        body: [
          "We keep your data while your account is active. When you delete your account, your personal data — structured records, document vectors, memory, and chat transcripts — is erased. Cached news is pruned automatically on a rolling basis.",
        ],
      },
      {
        heading: "Your rights (KVKK Art. 11)",
        body: [
          "You may request access to, correction of, or deletion of your data, and object to processing. You can erase everything yourself from Settings → Delete account, or contact us at " +
            CONTACT_EMAIL +
            ".",
        ],
      },
      {
        heading: "Security",
        body: [
          "Access is gated by authentication and every query is scoped to your account. We apply reasonable technical and organizational measures, though no method of transmission or storage is perfectly secure.",
        ],
      },
    ],
  },
  terms: {
    title: "Terms of Service",
    updated: `Last updated: ${EFFECTIVE}`,
    draftNote:
      "Draft template — informational only, not legal advice. Have a lawyer review before launch.",
    sections: [
      {
        heading: "The service",
        body: [
          `${COMPANY} is a personal-finance assistant that helps you track and understand your money with the help of AI. By using it you agree to these terms.`,
        ],
      },
      {
        heading: "Eligibility & account",
        body: [
          "You must be at least 18 years old. You are responsible for activity under your account and for keeping your credentials secure.",
        ],
      },
      {
        heading: "Acceptable use",
        body: [
          "Don't misuse the service: no unlawful activity, no attempts to break security or rate limits, no uploading content you have no right to share.",
        ],
      },
      {
        heading: "Not financial advice",
        body: [
          "The service is informational only and is not investment, legal, or tax advice. See our Disclaimer. You make your own decisions.",
        ],
      },
      {
        heading: "No warranty",
        body: [
          'The service is provided "as is" and "as available", without warranties of any kind. We do not guarantee accuracy, availability, or fitness for a particular purpose.',
        ],
      },
      {
        heading: "Limitation of liability",
        body: [
          `To the maximum extent permitted by law, ${COMPANY} and its operator are not liable for indirect, incidental, or consequential damages, or for any loss arising from your use of, or reliance on, the service.`,
        ],
      },
      {
        heading: "Changes & governing law",
        body: [
          `We may update these terms; continued use means you accept the changes. These terms are governed by the laws of the Republic of Türkiye. Questions: ${CONTACT_EMAIL}.`,
        ],
      },
    ],
  },
  refund: {
    title: "Delivery & Refund Policy",
    updated: `Last updated: ${EFFECTIVE}`,
    draftNote:
      "Draft template — a distance-sales / delivery & refund notice for the payment provider. Fill in the operator's legal details and have a lawyer review before launch.",
    sections: [
      {
        heading: "What you're buying",
        body: [
          `${COMPANY} Pro is a digital subscription that unlocks advanced features of the ${COMPANY} software service (a "digital product / virtual service"). There is no physical product and nothing is shipped.`,
          "The seller / service operator is [REGISTERED TRADE NAME / SOLE PROPRIETOR], [ADDRESS], [MERSIS / TAX NO]. Payments are collected through iyzico, an authorized payment institution; card data is handled by iyzico and is never stored on our servers.",
        ],
      },
      {
        heading: "Price & billing",
        body: [
          "The Pro plan is billed on a recurring monthly basis at the price shown on the pricing page (VAT included where applicable). We accept Visa and Mastercard credit/debit cards via iyzico.",
          "Your subscription renews automatically each period until you cancel. The price in effect at the time of each renewal applies.",
        ],
      },
      {
        heading: "Delivery",
        body: [
          "Delivery is electronic and immediate: once your payment is approved, your account is upgraded to Pro right away and the features become usable within the app. There is no shipment and therefore no delivery fee or delivery time beyond this instant activation.",
          `If your account is not upgraded within a few minutes of a successful payment, contact us at ${CONTACT_EMAIL} and we will resolve it or refund the charge.`,
        ],
      },
      {
        heading: "Right of withdrawal & refunds",
        body: [
          "Because Pro is digital content that starts being delivered electronically as soon as your payment is approved, the statutory right of withdrawal may not apply once you begin using it (Distance Contracts Regulation, Art. 15/1-ğ). Even so, we offer a goodwill refund: if you request a refund within 14 days of a charge and have not made substantial use of Pro features in that period, we will refund that payment.",
          "Refunds are issued to the original card via iyzico and typically appear within 1–10 business days depending on your bank.",
        ],
      },
      {
        heading: "Cancellation",
        body: [
          "You can cancel at any time from Settings, or by emailing us. Cancellation stops future renewals; your Pro access continues until the end of the period you already paid for. We do not pro-rate partial periods except under the goodwill refund above.",
        ],
      },
      {
        heading: "How to reach us",
        body: [
          `For any delivery, cancellation, or refund request, contact ${CONTACT_EMAIL} with the email on your account and the approximate date of the charge.`,
        ],
      },
    ],
  },
};

const TR: Bundle = {
  disclaimer: {
    title: "Sorumluluk Reddi — Yatırım Tavsiyesi Değildir",
    updated: `Son güncelleme: ${EFFECTIVE}`,
    draftNote:
      "Taslak şablon — yalnızca bilgilendirme amaçlıdır, hukuki tavsiye değildir. Yayına almadan önce bir avukata inceletin.",
    sections: [
      {
        heading: "Yalnızca eğitim/bilgilendirme amaçlı",
        body: [
          `${COMPANY}, kişisel finansını anlamana ve düzenlemene yardımcı olan eğitim ve bilgilendirme amaçlı bir araçtır. SPK veya başka bir merci nezdinde lisanslı yatırım danışmanlığı değildir ve ürettiği hiçbir şey kişiye özel yatırım tavsiyesi niteliği taşımaz.`,
          "Sana herhangi bir hisse, fon veya kripto varlığı al/sat/tut demeyiz. Sunulan rakam, özet ve senaryolar örnekleme amaçlıdır.",
        ],
      },
      {
        heading: "Yapay zekâ yanılabilir",
        body: [
          "Yanıtlar, büyük dil modelleri ve üçüncü taraf canlı piyasa/haber verileri yardımıyla üretilir. Eksik, güncel olmayan veya hatalı olabilir. Bir finansal karar vermeden önce daima bağımsız olarak doğrula.",
        ],
      },
      {
        heading: "Piyasalar risk içerir",
        body: [
          "Her yatırım, anaparanın kaybı dâhil risk içerir. Geçmiş performans gelecekteki sonuçları garanti etmez. Kararlarından ve sonuçlarından yalnızca sen sorumlusun.",
        ],
      },
      {
        heading: "Sorumluluğun reddi",
        body: [
          `Yürürlükteki hukukun izin verdiği azami ölçüde, ${COMPANY} ve işletmecisi, hizmete güvenerek verilen kararlardan doğan hiçbir zarardan sorumlu değildir. Gerçek finansal sonuç doğuran kararlar için lisanslı bir uzmana danış.`,
        ],
      },
    ],
  },
  privacy: {
    title: "Gizlilik Politikası & KVKK Aydınlatma Metni",
    updated: `Son güncelleme: ${EFFECTIVE}`,
    draftNote:
      "Taslak şablon — veri sorumlusu bilgilerini (resmi unvan, adres, VERBİS) doldur ve yayına almadan önce bir avukata inceletin.",
    sections: [
      {
        heading: "Veri sorumlusu",
        body: [
          `Veri sorumlusu [RESMİ UNVAN / ŞAHIS ŞİRKETİ], [ADRES], [VARSA VERBİS NO]'dur. Her türlü gizlilik talebi için: ${CONTACT_EMAIL}.`,
        ],
      },
      {
        heading: "Hangi verileri topluyoruz",
        body: [
          "- Hesap & kimlik: e-posta ve/veya kullanıcı adı, kimlik doğrulama tanımlayıcıları (Firebase Authentication aracılığıyla).",
          "- Profil: görünen ad, aylık gelir, risk skoru ve profili, avatar.",
          "- Girdiğin veya içe aktardığın finansal veriler: portföy varlıkları, işlemler, hesaplar ve bakiyeler, hedefler, abonelikler, izleme listesi.",
          "- Yüklenen belgeler: banka ekstreleri, makbuzlar ve benzeri dosyalar ile bunlardan çıkarılan metin.",
          "- Sohbetler: yapay zekâ koçuyla yaptığın mesajlar ve bunların geçmişi.",
          "- Teknik: hizmeti çalıştırmak ve güvenliğini sağlamak için gereken temel kayıtlar.",
        ],
      },
      {
        heading: "Neden işliyoruz (amaç & hukuki sebep)",
        body: [
          "Bu verileri; hizmeti sunmak, yapay zekâ yanıtları üretmek ve deneyimini kişiselleştirmek için işliyoruz. Hukuki sebep, seninle kurduğumuz sözleşmenin ifasıdır (KVKK m.5/2-c) ve gereken hâllerde (ör. sınır ötesi yapay zekâ işleme) açık rızandır (KVKK m.5/1).",
        ],
      },
      {
        heading: "Veri işleyenler & yurt dışına aktarım",
        body: [
          "Yanıt üretmek için mesajlarının içeriği ve yüklediğin belgelerden çıkarılan metin, işlenmek üzere Google Gemini API'sine gönderilir. Kimlik doğrulama için Google Firebase, barındırma için Google Cloud kullanılır. Bu, verilerin Türkiye dışında bulunabilecek sunuculara aktarılmasını içerir (KVKK m.9).",
          "Canlı piyasa ve haber sağlayıcılarına (ör. yfinance, NewsAPI, TEFAS, SEC EDGAR) yalnızca sorguların (ör. bir sembol) iletilir; kişisel finansal kayıtların gönderilmez.",
        ],
      },
      {
        heading: "Saklama süresi",
        body: [
          "Verilerini hesabın aktif olduğu sürece saklarız. Hesabını sildiğinde; yapılandırılmış kayıtların, belge vektörlerin, hafıza ve sohbet dökümlerin dâhil kişisel verilerin silinir. Önbelleğe alınan haberler periyodik olarak otomatik temizlenir.",
        ],
      },
      {
        heading: "Haklarınız (KVKK m.11)",
        body: [
          "Verilerine erişme, düzeltilmesini veya silinmesini isteme ve işlenmesine itiraz etme hakların vardır. Her şeyi kendin Ayarlar → Hesabı sil yolundan silebilir ya da " +
            CONTACT_EMAIL +
            " adresinden bize ulaşabilirsin.",
        ],
      },
      {
        heading: "Güvenlik",
        body: [
          "Erişim kimlik doğrulamayla korunur ve her sorgu yalnızca senin hesabına özeldir. Makul teknik ve idari tedbirleri uygularız; ancak hiçbir iletim veya saklama yöntemi tam olarak güvenli değildir.",
        ],
      },
    ],
  },
  terms: {
    title: "Kullanım Koşulları",
    updated: `Son güncelleme: ${EFFECTIVE}`,
    draftNote:
      "Taslak şablon — yalnızca bilgilendirme amaçlıdır, hukuki tavsiye değildir. Yayına almadan önce bir avukata inceletin.",
    sections: [
      {
        heading: "Hizmet",
        body: [
          `${COMPANY}, paranı yapay zekâ yardımıyla takip etmene ve anlamana yardımcı olan bir kişisel finans asistanıdır. Hizmeti kullanarak bu koşulları kabul etmiş olursun.`,
        ],
      },
      {
        heading: "Uygunluk & hesap",
        body: [
          "En az 18 yaşında olmalısın. Hesabın altındaki etkinlikten ve giriş bilgilerini güvende tutmaktan sen sorumlusun.",
        ],
      },
      {
        heading: "Kabul edilebilir kullanım",
        body: [
          "Hizmeti kötüye kullanma: hukuka aykırı faaliyet, güvenliği veya kullanım limitlerini aşma girişimi, paylaşma hakkın olmayan içerik yükleme yasaktır.",
        ],
      },
      {
        heading: "Yatırım tavsiyesi değildir",
        body: [
          "Hizmet yalnızca bilgilendirme amaçlıdır; yatırım, hukuk veya vergi tavsiyesi değildir. Sorumluluk Reddi metnimize bakın. Kararları sen verirsin.",
        ],
      },
      {
        heading: "Garanti verilmez",
        body: [
          'Hizmet "olduğu gibi" ve "mevcut hâliyle", hiçbir garanti verilmeksizin sunulur. Doğruluk, erişilebilirlik veya belirli bir amaca uygunluk garanti edilmez.',
        ],
      },
      {
        heading: "Sorumluluğun sınırlandırılması",
        body: [
          `Yürürlükteki hukukun izin verdiği azami ölçüde, ${COMPANY} ve işletmecisi; dolaylı, arızi veya sonuç niteliğindeki zararlardan ya da hizmeti kullanman veya ona güvenmenden doğan kayıplardan sorumlu değildir.`,
        ],
      },
      {
        heading: "Değişiklikler & uygulanacak hukuk",
        body: [
          `Bu koşulları güncelleyebiliriz; kullanmaya devam etmen değişiklikleri kabul ettiğin anlamına gelir. Bu koşullar Türkiye Cumhuriyeti hukukuna tabidir. Sorular: ${CONTACT_EMAIL}.`,
        ],
      },
    ],
  },
  refund: {
    title: "Teslimat & İade Şartları",
    updated: `Son güncelleme: ${EFFECTIVE}`,
    draftNote:
      "Taslak şablon — ödeme sağlayıcısı için mesafeli satış / teslimat ve iade bilgilendirmesi. İşletmecinin resmi bilgilerini doldur ve yayına almadan önce bir avukata inceletin.",
    sections: [
      {
        heading: "Ne satın alıyorsun",
        body: [
          `${COMPANY} Pro, ${COMPANY} yazılım hizmetinin gelişmiş özelliklerini açan dijital bir aboneliktir ("dijital ürün / sanal hizmet"). Fiziksel bir ürün yoktur ve hiçbir kargo gönderimi yapılmaz.`,
          "Satıcı / hizmet işletmecisi [RESMİ UNVAN / ŞAHIS ŞİRKETİ], [ADRES], [MERSİS / VERGİ NO]'dur. Ödemeler, yetkili ödeme kuruluşu iyzico üzerinden tahsil edilir; kart bilgilerin iyzico tarafından işlenir ve sunucularımızda saklanmaz.",
        ],
      },
      {
        heading: "Ücret & faturalandırma",
        body: [
          "Pro planı, fiyatlandırma sayfasında gösterilen bedel üzerinden aylık olarak tekrarlayan şekilde faturalandırılır (uygulanabilir olduğu yerde KDV dâhil). iyzico aracılığıyla Visa ve Mastercard kredi/banka kartlarını kabul ediyoruz.",
          "Aboneliğin, sen iptal edene kadar her dönem otomatik olarak yenilenir. Her yenilemede o an geçerli olan fiyat uygulanır.",
        ],
      },
      {
        heading: "Teslimat",
        body: [
          "Teslimat elektroniktir ve anında yapılır: ödemen onaylandığı anda hesabın Pro'ya yükseltilir ve özellikler uygulama içinde hemen kullanılabilir hâle gelir. Fiziksel gönderim olmadığından bu anlık aktivasyon dışında bir teslimat ücreti veya süresi yoktur.",
          `Başarılı bir ödemeden birkaç dakika sonra hesabın yükseltilmezse ${CONTACT_EMAIL} adresinden bize ulaş; sorunu çözer veya ücreti iade ederiz.`,
        ],
      },
      {
        heading: "Cayma hakkı & iade",
        body: [
          "Pro, ödemen onaylanır onaylanmaz elektronik olarak teslim edilmeye başlanan dijital içerik olduğundan, kullanmaya başladıktan sonra yasal cayma hakkı uygulanmayabilir (Mesafeli Sözleşmeler Yönetmeliği m.15/1-ğ). Buna rağmen bir iyi niyet iadesi sunuyoruz: bir tahsilattan itibaren 14 gün içinde iade talep edersen ve bu sürede Pro özelliklerini esaslı biçimde kullanmadıysan, o ödemeyi iade ederiz.",
          "İadeler, iyzico üzerinden ödemenin yapıldığı karta yapılır ve bankana bağlı olarak genellikle 1–10 iş günü içinde hesabına yansır.",
        ],
      },
      {
        heading: "İptal",
        body: [
          "Ayarlar'dan ya da bize e-posta göndererek istediğin an iptal edebilirsin. İptal, gelecekteki yenilemeleri durdurur; zaten ödediğin dönemin sonuna kadar Pro erişimin devam eder. Yukarıdaki iyi niyet iadesi dışında, kısmi dönemler için orantılı geri ödeme yapılmaz.",
        ],
      },
      {
        heading: "Bize ulaş",
        body: [
          `Her türlü teslimat, iptal veya iade talebi için hesabındaki e-posta ve tahsilatın yaklaşık tarihiyle birlikte ${CONTACT_EMAIL} adresinden bize ulaş.`,
        ],
      },
    ],
  },
};

// Registry keyed by language. To add a language later, translate a Bundle and
// add it here — untranslated languages gracefully fall back to English.
const BUNDLES: Partial<Record<SupportedLanguage, Bundle>> = { en: EN, tr: TR };

export function getLegalDoc(lang: SupportedLanguage, slug: LegalSlug): LegalDoc {
  const bundle = BUNDLES[lang] ?? EN;
  return bundle[slug];
}

export const LEGAL_SLUGS: LegalSlug[] = ["privacy", "terms", "disclaimer", "refund"];
