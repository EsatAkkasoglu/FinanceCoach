/**
 * Shared status / "oops" page. The layout is constant; the message changes by
 * the ?reason= query (coming_soon | checkout_error | payment_failed | generic).
 * Reached when Pro checkout can't proceed — e.g. payments not wired yet. While
 * the user is here, they can play a tiny game.
 */
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Clock, AlertTriangle, ArrowLeft } from "lucide-react";

import { getLanguageFromPath, buildLocalizedPath, type SupportedLanguage } from "@/lib/routing";
import { MiniGame } from "./MiniGame";

const REASONS = ["coming_soon", "checkout_error", "payment_failed", "generic"] as const;
type Reason = (typeof REASONS)[number];

export function OopsPage() {
  const { t } = useTranslation("billing");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const lang: SupportedLanguage = getLanguageFromPath(window.location.pathname) ?? "en";

  const raw = params.get("reason") ?? "generic";
  const reason: Reason = (REASONS as readonly string[]).includes(raw) ? (raw as Reason) : "generic";

  const isComingSoon = reason === "coming_soon";
  const Icon = isComingSoon ? Clock : AlertTriangle;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[hsl(var(--bg))] px-4 py-12">
      <div className="w-full max-w-md text-center">
        <span
          className={`mx-auto flex h-14 w-14 items-center justify-center rounded-2xl ${
            isComingSoon ? "bg-accent/15 text-accent" : "bg-amber-500/15 text-amber-500"
          }`}
        >
          <Icon className="h-7 w-7" />
        </span>
        <h1 className="mt-5 font-display text-h3 font-bold tracking-tight">
          {t(`oops.title.${reason}`)}
        </h1>
        <p className="mx-auto mt-3 max-w-sm text-body-sm text-content-muted">
          {t(`oops.body.${reason}`)}
        </p>

        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            onClick={() => navigate(buildLocalizedPath(lang, "/dashboard"))}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-glow transition hover:opacity-90"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("oops.back")}
          </button>
          <button
            onClick={() => navigate(buildLocalizedPath(lang, "/pricing"))}
            className="inline-flex items-center rounded-xl border border-line px-5 py-2.5 text-sm font-medium text-content transition hover:bg-surface-raised"
          >
            {t("oops.backPricing")}
          </button>
        </div>

        <MiniGame />
      </div>
    </div>
  );
}
