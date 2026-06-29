/** Settings card: shows the current plan and starts a Pro checkout. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { Sparkles, Loader2, Check } from "lucide-react";

import { getBillingPlans, startCheckout, type BillingPlan } from "@/lib/api";
import { getLanguageFromPath, buildLocalizedPath } from "@/lib/routing";

export function UpgradeCard() {
  const { t } = useTranslation("billing");
  const location = useLocation();
  const navigate = useNavigate();
  const lang = getLanguageFromPath(location.pathname) ?? "en";

  const [tier, setTier] = useState<string>("free");
  const [plan, setPlan] = useState<BillingPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let alive = true;
    void getBillingPlans().then((res) => {
      if (!alive || !res) return;
      setTier(res.tier);
      setPlan(res.plans.find((p) => p.code === "pro") ?? null);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  function toOops(reason: string) {
    navigate(buildLocalizedPath(lang, `/oops?reason=${reason}`));
  }

  async function upgrade() {
    setStarting(true);
    const returnUrl = `${window.location.origin}${buildLocalizedPath(lang, "/billing/return")}`;
    const res = await startCheckout("pro", returnUrl);
    if (res.status === "ok") {
      window.location.href = res.redirectUrl;
      return;
    }
    setStarting(false);
    // Payments not wired yet → "coming soon"; anything else → generic checkout error.
    toOops(res.status === "unavailable" ? "coming_soon" : "checkout_error");
  }

  if (loading) return null;

  const isPro = tier === "pro";
  const price = plan ? `${plan.price.toLocaleString()} ${plan.currency}` : "";

  return (
    <div className="rounded-xl border border-accent/30 bg-accent/5 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-accent" />
            {t("planLabel")}: {isPro ? t("pro") : t("free")}
          </p>
          <p className="mt-1 text-xs text-content-muted">
            {isPro ? t("currentPro") : t("upgradeDesc")}
          </p>
        </div>
        {isPro ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent/15 px-3 py-1.5 text-xs font-medium text-accent">
            <Check className="h-3.5 w-3.5" />
            {t("pro")}
          </span>
        ) : (
          <button
            onClick={upgrade}
            disabled={starting}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-xs font-semibold text-white shadow-glow transition hover:opacity-90 disabled:opacity-60"
          >
            {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {t("upgrade")}{price ? ` · ${price}${t("perMonth")}` : ""}
          </button>
        )}
      </div>
    </div>
  );
}
