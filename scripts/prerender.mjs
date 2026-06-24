// scripts/prerender.mjs
// Post-build prerender. After `vite build`, emit per-language static HTML for
// `/`, `/en`, and `/tr` with localized <head> meta (title, description,
// canonical, Open Graph, Twitter) plus a no-JS <noscript> marketing fallback,
// so crawlers, social scrapers, and AI answer-engines get language-specific,
// content-rich HTML instead of an empty SPA shell. Touches no app code.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const indexPath = join(dist, "index.html");
const ORIGIN = "https://fincoach-esat.web.app";

if (!existsSync(indexPath)) {
  console.error("[prerender] dist/index.html not found - run `vite build` first.");
  process.exit(1);
}

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const loadLanding = (lang) =>
  JSON.parse(
    readFileSync(join(root, "src", "i18n", "locales", lang, "landing.json"), "utf8"),
  );

const SEO = {
  en: {
    title: "FinCoach — AI finance coach for portfolio, budget & goals",
    description:
      "FinCoach is your AI finance coach — track your portfolio, budget, and funds, set goals, and get clear answers backed by real market data and citations.",
    ogTitle: "FinCoach — your AI finance coach",
    ogDescription:
      "Portfolio, budget, funds, and goals — explained in plain language with citations you can verify. Free while in beta.",
    ogLocale: "en_US",
    ctaHref: "/en/dashboard",
    cta: "Get started free",
  },
  tr: {
    title: "FinCoach — yapay zekâ finans koçu: portföy, bütçe, hedefler",
    description:
      "FinCoach yapay zekâ finans koçun — portföyünü, bütçeni ve fonlarını takip et, hedefler belirle ve gerçek piyasa verisine dayalı, kaynaklı net yanıtlar al.",
    ogTitle: "FinCoach — yapay zekâ finans koçun",
    ogDescription:
      "Portföy, bütçe, fonlar ve hedefler — kaynaklarıyla, sade bir dille açıklanır. Beta sürecinde ücretsiz.",
    ogLocale: "tr_TR",
    ctaHref: "/tr/dashboard",
    cta: "Ücretsiz başla",
  },
};

function noscriptBlock(lang) {
  const L = loadLanding(lang);
  const s = SEO[lang];
  const feats = (L.features?.items || [])
    .map((it) => `<li><strong>${esc(it.title)}</strong> — ${esc(it.desc)}</li>`)
    .join("");
  const sources = (L.trust?.sources || []).map(esc).join(" · ");
  return (
    `<noscript><main>` +
    `<h1>${esc(L.hero.titleLead)} ${esc(L.hero.titleAccent)}</h1>` +
    `<p>${esc(L.hero.subtitle)}</p>` +
    `<p><a href="${s.ctaHref}">${esc(s.cta)}</a></p>` +
    `<h2>${esc(L.features.title)}</h2><ul>${feats}</ul>` +
    (sources ? `<p>${esc(L.trust.label)}: ${sources}</p>` : "") +
    `</main></noscript>`
  );
}

function sub(html, re, replacement, label) {
  if (!re.test(html)) {
    console.warn(`[prerender] pattern not found (${label})`);
    return html;
  }
  return html.replace(re, replacement);
}

function render(baseHtml, lang, canonicalPath) {
  const s = SEO[lang];
  const canonical = `${ORIGIN}${canonicalPath}`;
  let h = baseHtml;
  h = sub(h, /<html lang="[^"]*"/, `<html lang="${lang}"`, "html lang");
  h = sub(h, /<title>[\s\S]*?<\/title>/, `<title>${esc(s.title)}</title>`, "title");
  h = sub(h, /<meta\s+name="description"[\s\S]*?\/>/, `<meta name="description" content="${esc(s.description)}" />`, "description");
  h = sub(h, /<link\s+rel="canonical"[\s\S]*?\/>/, `<link rel="canonical" href="${canonical}" />`, "canonical");
  h = sub(h, /<meta\s+property="og:title"[\s\S]*?\/>/, `<meta property="og:title" content="${esc(s.ogTitle)}" />`, "og:title");
  h = sub(h, /<meta\s+property="og:description"[\s\S]*?\/>/, `<meta property="og:description" content="${esc(s.ogDescription)}" />`, "og:description");
  h = sub(h, /<meta\s+property="og:url"[\s\S]*?\/>/, `<meta property="og:url" content="${canonical}" />`, "og:url");
  h = sub(h, /<meta\s+property="og:locale"\s+content="[^"]*"\s*\/>/, `<meta property="og:locale" content="${s.ogLocale}" />`, "og:locale");
  h = sub(h, /<meta\s+name="twitter:title"[\s\S]*?\/>/, `<meta name="twitter:title" content="${esc(s.ogTitle)}" />`, "twitter:title");
  h = sub(h, /<meta\s+name="twitter:description"[\s\S]*?\/>/, `<meta name="twitter:description" content="${esc(s.ogDescription)}" />`, "twitter:description");
  h = h.replace(/<\/body>/, `    ${noscriptBlock(lang)}\n  </body>`);
  return h;
}

const base = readFileSync(indexPath, "utf8");

// Root "/" keeps English meta + canonical "/", gains the no-JS fallback.
writeFileSync(indexPath, base.replace(/<\/body>/, `    ${noscriptBlock("en")}\n  </body>`));

for (const lang of ["en", "tr"]) {
  mkdirSync(join(dist, lang), { recursive: true });
  writeFileSync(join(dist, lang, "index.html"), render(base, lang, `/${lang}`));
  console.log(`[prerender] wrote dist/${lang}/index.html`);
}
console.log("[prerender] done - /, /en, /tr");
