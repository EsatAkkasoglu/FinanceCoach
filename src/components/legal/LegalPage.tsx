/**
 * Renders a single legal document (privacy / terms / disclaimer) for the
 * language in the route. Works both logged-out (marketing) and logged-in.
 */
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import { getLanguageFromPath, isSupportedLanguage, type SupportedLanguage } from "@/lib/routing";
import {
  getLegalDoc,
  LEGAL_SLUGS,
  type LegalSlug,
} from "./legalContent";

type Chrome = { back: string; eyebrow: string; nav: Record<LegalSlug, string> };

// Partial + EN fallback so adding a SupportedLanguage never breaks the build;
// untranslated languages degrade to the English chrome.
const CHROME: Partial<Record<SupportedLanguage, Chrome>> = {
  en: {
    back: "Back",
    eyebrow: "Legal",
    nav: { privacy: "Privacy & KVKK", terms: "Terms", disclaimer: "Disclaimer" },
  },
  tr: {
    back: "Geri",
    eyebrow: "Yasal",
    nav: { privacy: "Gizlilik & KVKK", terms: "Koşullar", disclaimer: "Sorumluluk Reddi" },
  },
};

function Paragraph({ text }: { text: string }) {
  if (text.startsWith("- ")) {
    return <li className="ml-1 text-body-sm text-content-muted">{text.slice(2)}</li>;
  }
  return <p className="text-body-sm leading-relaxed text-content-muted">{text}</p>;
}

export function LegalPage() {
  const params = useParams();
  const navigate = useNavigate();

  // When logged out, this renders OUTSIDE <Routes>, so useParams() is empty —
  // fall back to parsing the path (/:lang/legal/:doc).
  const segments = window.location.pathname.split("/").filter(Boolean);
  const lang: SupportedLanguage = isSupportedLanguage(params.lang)
    ? params.lang
    : getLanguageFromPath(window.location.pathname) ?? "en";

  const rawDoc = params.doc ?? segments[segments.length - 1] ?? "";
  const slug: LegalSlug = (LEGAL_SLUGS as string[]).includes(rawDoc)
    ? (rawDoc as LegalSlug)
    : "privacy";

  const doc = useMemo(() => getLegalDoc(lang, slug), [lang, slug]);
  const chrome = CHROME[lang] ?? CHROME.en!;

  return (
    <div className="min-h-screen bg-[hsl(var(--bg))] px-4 py-10 sm:px-6">
      <div className="mx-auto max-w-3xl">
        <button
          onClick={() => navigate(`/${lang}`)}
          className="inline-flex items-center gap-2 text-sm font-medium text-content-muted transition hover:text-content"
        >
          <ArrowLeft className="h-4 w-4" />
          {chrome.back}
        </button>

        {/* Doc switcher */}
        <nav className="mt-6 flex flex-wrap gap-2">
          {LEGAL_SLUGS.map((s) => (
            <button
              key={s}
              onClick={() => navigate(`/${lang}/legal/${s}`)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                s === slug
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-line text-content-muted hover:text-content"
              }`}
            >
              {chrome.nav[s]}
            </button>
          ))}
        </nav>

        <header className="mt-8">
          <p className="text-overline uppercase tracking-wide text-content-muted">{chrome.eyebrow}</p>
          <h1 className="mt-2 font-display text-h2 font-bold tracking-tight">{doc.title}</h1>
          <p className="mt-1 text-caption text-content-muted">{doc.updated}</p>
        </header>

        {/* Draft / not-legal-advice banner */}
        <div className="mt-6 flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <p className="text-caption text-content">{doc.draftNote}</p>
        </div>

        <article className="mt-8 space-y-8 pb-16">
          {doc.sections.map((section) => {
            const isList = section.body.every((b) => b.startsWith("- "));
            return (
              <section key={section.heading}>
                <h2 className="text-h5 font-semibold">{section.heading}</h2>
                {isList ? (
                  <ul className="mt-3 list-disc space-y-1.5 pl-5">
                    {section.body.map((b, i) => (
                      <Paragraph key={i} text={b} />
                    ))}
                  </ul>
                ) : (
                  <div className="mt-3 space-y-3">
                    {section.body.map((b, i) => (
                      <Paragraph key={i} text={b} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </article>
      </div>
    </div>
  );
}
