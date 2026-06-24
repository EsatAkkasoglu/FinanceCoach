# FinCoach — SEO, Technical, AI-Visibility & Brand Audit + 90-Day Plan

**Site:** https://fincoach-esat.web.app · **Stack:** Vite + React SPA on Firebase Hosting · **Audit date:** 2026-06-24

> Combines five lenses requested: SEO audit, technical SEO, AI visibility (GEO/AEO), brand review, and a campaign plan. Findings are grounded in the actual repo (`index.html`, `public/`, `LandingPage.tsx`, i18n, `firebase.json`), not assumptions.

---

## Executive summary

FinCoach has a genuinely strong **product and marketing surface** — clear positioning ("your AI finance coach"), a consistent plain-language voice, a proper `<h1>` + heading hierarchy on the landing page, citation-led trust messaging, and per-route `<title>` updates already wired in `App.tsx`. The content quality bar is high.

The problem was almost entirely in the **machine-readable layer**: the single `index.html` that every crawler, social scraper, and AI answer-engine sees first was bare — a generic `FinCoach` title, **no meta description, no canonical, no Open Graph/Twitter cards, no structured data, no `robots.txt`, no `sitemap.xml`, no favicon** (still the default Vite logo). For a client-rendered SPA this is the highest-leverage gap, because non-JS crawlers and link-preview bots only ever read that shell.

**Top 3 priorities (all shipped in this pass):**
1. Rich `index.html` meta + Open Graph/Twitter cards → real titles, descriptions, and link previews.
2. JSON-LD structured data (Organization, WebSite, SoftwareApplication, FAQ) → AI/answer-engine extractability.
3. `robots.txt` + `sitemap.xml` + web manifest + branded favicon/OG image → crawlability, indexation, and shareability.

**Overall assessment:** *Strong foundation, was under-instrumented for discovery.* The quick wins are now done; the strategic work is prerendering/SSR for the SPA and a TR/EN content engine.

---

## What changed in this commit

| File | Change |
|---|---|
| `index.html` | Descriptive title (61 chars), meta description (151 chars), keywords, canonical, robots directives, `hreflang` (en/tr/x-default), theme-color, favicon/apple-touch/manifest links, full Open Graph + Twitter cards, and JSON-LD `@graph` (Organization · WebSite · SoftwareApplication · FAQ ×4). |
| `public/robots.txt` | Allow-all + `Disallow: /api/`, explicit allow for AI crawlers (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended, Applebot-Extended), sitemap reference. |
| `public/sitemap.xml` | Home + `/en` + `/tr` with `xhtml:link` hreflang alternates. |
| `public/site.webmanifest` | PWA manifest — name, theme/background color, categories, 192/512 + maskable icons. |
| `public/favicon.svg` | Brand mark (green tile + upward trend line) replacing the default Vite logo. |
| `public/og-image.png` | 1200×630 branded social share image. |
| `public/icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | App/PWA/Apple icons. |

---

## Keyword opportunities

No SEO data tool is connected, so difficulty/volume are **directional** (connect Ahrefs or Semrush via MCP for exact numbers — both appeared available in this session). Intent and relevance are high-confidence.

| Keyword | Difficulty | Opportunity | Intent | Recommended content |
|---|---|---|---|---|
| ai finance coach | Moderate | High | Commercial | Home / pillar page (own the category term) |
| ai finance app | Hard | Medium | Commercial | Home + comparison page |
| ai budgeting app | Hard | Medium | Commercial | "Smart budgeting" feature page |
| portfolio tracker with ai | Moderate | High | Commercial | Portfolio feature page |
| tefas fon analizi (TR) | Easy | High | Commercial | TR funds landing page |
| tefas fon karşılaştırma (TR) | Easy | High | Commercial | TR fund-comparison tool page |
| yapay zeka finans koçu (TR) | Easy | High | Commercial | TR home (category term, low competition) |
| how to track my portfolio | Moderate | Medium | Informational | Guide / blog |
| how to make a budget in lira | Easy | High | Informational | TR + EN guide |
| best free finance app | Hard | Medium | Commercial | Comparison / alternatives page |
| explain my investments | Easy | Medium | Informational | "AI coach" use-case page |
| pdf bank statement to budget | Easy | High | Transactional | "Document import" feature page |
| emergency fund calculator | Moderate | High | Transactional | Interactive tool (link-magnet) |
| compound interest goal planner | Moderate | High | Transactional | Interactive tool (link-magnet) |
| fear and greed index explained | Easy | Medium | Informational | Glossary / blog |
| what is a specialist ai agent | Easy | Low | Informational | About / how-it-works |

**Long-tail / question (AEO) targets to answer on-page:** "is FinCoach free", "where does FinCoach get its data", "is FinCoach financial advice", "how to compare TEFAS funds", "ai app that explains stock moves". The first three are now in the FAQ JSON-LD.

---

## On-page issues (before → fix)

| Item | Before | Severity | Status |
|---|---|---|---|
| `<title>` | `FinCoach` (generic, no keywords) | High | ✅ Fixed — keyword-rich, 61 chars |
| Meta description | Missing | Critical | ✅ Fixed — 151 chars |
| Canonical | Missing | High | ✅ Fixed |
| Open Graph / Twitter | Missing (no link previews) | High | ✅ Fixed — full cards + 1200×630 image |
| Structured data | Missing | High | ✅ Fixed — 4 schema types |
| Favicon | Default `vite.svg` | Medium | ✅ Fixed — branded SVG + PNGs |
| `hreflang` (en/tr) | Missing despite bilingual routes | Medium | ✅ Fixed in `index.html` + sitemap |
| `<h1>` on landing | Present (`motion.h1`) | — | ✅ Already good |
| Per-route `<title>` | Present (`App.tsx`) | — | ✅ Already good |
| Per-route meta description | Missing (SPA) | Medium | ⚠️ Recommended (see strategic) |
| `<html lang>` on TR switch | Hardcoded `en`, never updated | Low | ⚠️ Recommended (1-line `useEffect`) |

---

## Technical SEO checklist

| Check | Status | Detail |
|---|---|---|
| HTTPS | ✅ Pass | Firebase Hosting, HTTPS enforced |
| Mobile viewport | ✅ Pass | Present in `index.html` |
| robots.txt | ✅ Pass | Added |
| XML sitemap | ✅ Pass | Added, hreflang-annotated |
| Canonical tags | ✅ Pass | Added |
| Structured data | ✅ Pass | Validates as JSON; test in Google Rich Results |
| Favicon / PWA manifest | ✅ Pass | Added |
| Font loading | ✅ Pass | `preconnect` + `display=swap` already present |
| SPA indexability | ⚠️ Warning | Content is JS-rendered; Google renders JS but most AI/social bots do not — static meta + JSON-LD now mitigate. Prerender for full coverage. |
| Soft-404s | ⚠️ Warning | `firebase.json` rewrites `**` → `index.html` (200). Unknown URLs never 404. Acceptable for an app; add a real not-found view if marketing URLs proliferate. |
| Core Web Vitals | ❓ Verify | Heavy Three.js/WebGL on landing — already lazy-loaded + reduced-motion gated (good). Measure LCP/INP/CLS with PageSpeed Insights post-deploy. |

---

## AI visibility (GEO / AEO)

How FinCoach shows up in ChatGPT, Claude, Gemini, and Perplexity answers.

- **Structured identity (now fixed):** `SoftwareApplication` + `Organization` JSON-LD tells answer-engines exactly what FinCoach is, its category (`FinanceApplication`), price (free/beta), and feature list — the facts an LLM needs to describe and recommend it.
- **FAQ schema (now fixed):** four Q&As ("what is it", "cost", "data sources", "is it advice") give answer-engines liftable, citable Q&A pairs — the format AEO rewards.
- **Crawler access (now fixed):** `robots.txt` explicitly welcomes GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended, and Applebot-Extended, so training/retrieval crawlers aren't blocked by default.
- **Next for AEO:** publish comparison + "best ai finance app" pages with clear, extractable claims and a sources section; keep the citation-led voice (LLMs favor content that itself cites sources). Seed a few authoritative mentions (Product Hunt, GitHub README, a launch post) so models have corroborating references.

---

## Brand voice review

Voice is **consistent and on-strategy** across the landing copy — clear, plain-language, trustworthy, and citation-forward. No major deviations.

- **Product descriptor** is stable: "your AI finance coach." Keep this exact phrase as the category anchor across meta, app stores, and PR. (Used verbatim in the new meta/OG.)
- **Proof > hype:** copy leans on "answers you can verify / sources on every answer" rather than performance claims. The new meta mirrors this.
- **Disclaimer integrity:** the site is explicit that it is "a hackathon prototype — not financial advice." The new FAQ schema includes an "Is FinCoach financial advice? → No" entry, so the disclaimer travels into search/AI surfaces too. Keep meta free of advice-implying language (done).
- **Minor flags:** testimonials are attributed to named beta testers ("Elif Y.", "Marcus T."). Ensure these are real and consented before scaling distribution. "100% answers with citations" is a strong absolute — keep it literally true.

---

## Content gaps & 90-day campaign plan

**Goal:** turn a high-quality but invisible app into a discoverable one — own "ai finance coach" (EN) and "yapay zeka finans koçu / tefas fon analizi" (TR), and become AI-recommendable.

### Quick wins (this week — under 2 hrs each)
- Submit `sitemap.xml` to Google Search Console + Bing Webmaster Tools; request indexing of `/`, `/en`, `/tr`.
- Validate the new structured data in Google's Rich Results Test and the OG image in the LinkedIn Post Inspector / X Card Validator.
- Add the live URL + OG image to the GitHub repo README and the repo "About" (cheap, authoritative backlinks AI crawlers read).
- Run PageSpeed Insights on the landing page; note LCP/INP for the WebGL hero.
- Post a launch note (Product Hunt / Reddit r/personalfinance-TR / LinkedIn) pointing at the now-rich link preview.

### Strategic investments (this quarter)
- **Prerender the marketing routes.** Add `vite-plugin-prerender` (or a prerender step) for `/`, `/en`, `/tr` so bots get fully-rendered HTML, not a shell. Biggest single SEO unlock for an SPA. *(High impact, half-day.)*
- **Per-route meta.** A tiny dependency-free `useSeo({title, description})` hook (extend the existing `document.title` logic in `App.tsx`) that also sets `<meta name="description">` and updates `<html lang>` on TR/EN switch. *(Medium impact, half-day.)*
- **TR funds content cluster.** "TEFAS fon analizi", "TEFAS fon karşılaştırma", "en iyi TEFAS fonları" — low competition, high intent, directly matches a built feature. *(High impact, multi-day.)*
- **Two interactive tools as link-magnets.** Emergency-fund and compound-interest/goal planners (the calc layer already exists in `backend/app/tools/calc_tools.py`) — standalone indexable pages that earn links. *(High impact, multi-day.)*
- **Pillar + how-it-works pages** targeting "ai finance coach" and "how does an ai finance coach work", interlinked with feature pages.

### 12-week calendar (skeleton)
| Weeks | Focus | Output |
|---|---|---|
| 1–2 | Indexation + prerender | GSC/Bing setup, prerender PR, per-route meta hook |
| 3–6 | TR funds cluster | 3–4 TEFAS pages (TR), interlinked, schema'd |
| 5–8 | Link-magnet tools | Emergency-fund + goal-planner pages, launch posts |
| 7–10 | EN pillar + comparisons | "ai finance coach" pillar, "best free finance app" comparison |
| 9–12 | AEO + measure | FAQ expansion, authoritative mentions, CWV pass, rank/impression review |

**Success metrics:** indexed pages, impressions/clicks (GSC), rankings for the target set above, share-of-voice in AI answers (spot-check ChatGPT/Perplexity for "best ai finance coach"), and CWV pass rate.

---

## Verify after deploy
1. `pnpm build` → confirm `dist/` contains `index.html` (with meta), `robots.txt`, `sitemap.xml`, `site.webmanifest`, and all icons (Vite copies `public/` verbatim).
2. Deploy, then test: Google Rich Results Test (JSON-LD), PageSpeed Insights (CWV), and a link-preview validator (OG image).
3. Submit the sitemap in Search Console.

*Generated as part of the SEO/marketing pass on 2026-06-24. Not financial advice.*

---

## Live competitive landscape (Exa research · 2026-06-24)

Live web research (via Exa) sharpened the keyword section and surfaced a positioning risk.

**The "multi-agent AI coach + citations" pitch is now crowded (EN).** Several products use almost exactly FinCoach's framing:

| Competitor | Overlap with FinCoach |
|---|---|
| [Parthean](https://www.parthean.com/client-app) | AI agents, "talk to your money", answers with citations + sources |
| [Beelinger](https://beelinger.com/personal-finance-app/) | "Command center" with **6 specialized AI coaches**, grounded in your data |
| [Richify](https://www.richify.ai/best-ai-personal-finance-app) | Markets "**Felix + 7 specialists**" — nearly identical to "seven specialist agents" |
| [Klaris](https://useklaris.com/) | AI "grounded in your real data, not internet-scraped generalities" |
| [Penny](https://apps.apple.com/us/app/penny-ai-portfolio-coach/id6758650986) | AI money coach, **Turkish language**, PDF scan — closest cross-market threat (US-tax focused, no TEFAS) |

Established players AI engines actually recommend: Monarch, Copilot, YNAB, Cleo, Rocket Money, Empower.

**Takeaway:** "7 specialist agents + citations" reads as table stakes now. The defensible wedge is the **intersection almost no one occupies: AI coach + TEFAS funds + multi-currency (₺/$/€) + citations.**

**The Turkish fund space is active but split** — and mostly *without* a conversational AI-coach-with-citations layer:

- Fund comparison/analysis: [Fonaly](https://www.fonaly.com/fon-karsilastirma), [Fonoloji](https://fonoloji.com/), [Borsafolio](https://borsafolio.com/) (2000+ funds), [Fonmap](https://www.fonmap.com/), Pusula
- Emerging MCP-for-funds (matches this repo's LangChain/MCP thesis): [Neye Yatırım](https://neyeyatirim.com/), [FonTakip MCP](https://mcp.fontakip.com.tr/)

The presence of multiple dedicated "TEFAS fon karşılaştırma / fon analizi" competitor pages **validates that keyword cluster** — confirming the TR content strategy in the 90-day plan.

### Action taken from this research
- Shipped `public/tr/fon-karsilastirma.html` — a static, crawlable Turkish landing page targeting "TEFAS fon karşılaştırma / fon analizi" with FAQ schema, positioning FinCoach on the TEFAS + AI-coach + citations wedge. Added to `sitemap.xml`.

### Next moves (highest leverage)
1. **AEO:** FinCoach is absent from every "best AI finance app 2026" roundup ([Richify](https://www.richify.ai/best-ai-personal-finance-app), [FinWise Hub](https://finwisehub.co/best-ai-personal-finance-apps-2026), [MoneyReportAI](https://moneyreportai.com/best-ai-apps-personal-finance-2026/), [Vera](https://veramoney.com/blog/best-ai-money-tools-in-2026)) — these are exactly what ChatGPT/Perplexity cite. Pitch for inclusion, and publish your own honest comparison page.
2. **Reposition TR pages** to lead with TEFAS + multi-currency, not "7 agents."
3. **Expand the TR fund cluster** (fon analizi, en iyi TEFAS fonları, BES fonu karşılaştırma) around this first page as a topic cluster.
