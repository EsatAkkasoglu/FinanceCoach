/**
 * Standalone, public pricing page at /:lang/pricing — a deep-linkable URL that
 * shows product + price (for the iyzico merchant review) without requiring login.
 * Reuses the landing PricingSection so there's a single source of truth.
 */
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import {
  buildLocalizedPath,
  getLanguageFromPath,
  type SupportedLanguage,
} from "@/lib/routing";
import { PricingSection, Wordmark } from "./LandingPage";

const LANGS: SupportedLanguage[] = ["tr", "en"];

export function PricingPage() {
  const { t, i18n } = useTranslation("landing");
  const { t: tc } = useTranslation("common");
  const navigate = useNavigate();
  const location = useLocation();
  const lang: SupportedLanguage = getLanguageFromPath(location.pathname) ?? "en";

  const go = (path: string) => navigate(buildLocalizedPath(lang, path));
  const switchLang = (next: SupportedLanguage) => {
    void i18n.changeLanguage(next);
    navigate(`/${next}/pricing`, { replace: true });
  };

  return (
    <div className="min-h-screen bg-[hsl(var(--bg))]">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-line bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <button onClick={() => go("/")} aria-label="FinCoach">
            <Wordmark />
          </button>
          <div className="flex items-center gap-2">
            {LANGS.map((l) => (
              <button
                key={l}
                onClick={() => switchLang(l)}
                className={`rounded-md px-2 py-1 text-xs font-medium transition ${
                  lang === l ? "text-accent" : "text-content-muted hover:text-content"
                }`}
              >
                {l.toUpperCase()}
              </button>
            ))}
            <button
              onClick={() => go("/login")}
              className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-content transition hover:border-accent/40 hover:text-accent"
            >
              {t("nav.signIn", { defaultValue: lang === "tr" ? "Giriş yap" : "Sign in" })}
            </button>
          </div>
        </div>
      </header>

      <main>
        <PricingSection onRegister={() => go("/register")} />
      </main>

      {/* Minimal footer with legal — useful context for the payment review. */}
      <footer className="border-t border-line px-4 py-8 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="rounded-xl border border-line bg-bg/50 px-4 py-3 text-center text-caption text-content-muted">
            {tc("disclaimer")}
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-caption text-content-muted">
            <button onClick={() => go("/legal/privacy")} className="transition hover:text-content">
              {lang === "tr" ? "Gizlilik & KVKK" : "Privacy & KVKK"}
            </button>
            <button onClick={() => go("/legal/terms")} className="transition hover:text-content">
              {lang === "tr" ? "Kullanım Koşulları" : "Terms"}
            </button>
            <button onClick={() => go("/legal/disclaimer")} className="transition hover:text-content">
              {lang === "tr" ? "Sorumluluk Reddi" : "Disclaimer"}
            </button>
            <a href="mailto:hello@fincoach.app" className="transition hover:text-content">
              hello@fincoach.app
            </a>
          </div>
          <p className="mt-4 text-center text-caption text-content-muted">
            © {new Date().getFullYear()} FinCoach
          </p>
        </div>
      </footer>
    </div>
  );
}
