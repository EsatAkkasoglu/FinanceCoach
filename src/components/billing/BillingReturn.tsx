/** Post-checkout return page: confirms the payment and shows the result. */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

import { finalizeCheckout } from "@/lib/api";
import { getLanguageFromPath, buildLocalizedPath, type SupportedLanguage } from "@/lib/routing";

type Status = "verifying" | "success" | "failed";

export function BillingReturn() {
  const { t } = useTranslation("billing");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [status, setStatus] = useState<Status>("verifying");
  const ran = useRef(false);

  const lang: SupportedLanguage = getLanguageFromPath(window.location.pathname) ?? "en";
  // iyzico posts a "token"; the mock provider passes "ref". Accept either.
  const ref = params.get("token") ?? params.get("ref") ?? "";

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!ref) {
      setStatus("failed");
      return;
    }
    const extra: Record<string, string> = {};
    const conv = params.get("conversationId");
    if (conv) extra.conversationId = conv;
    void finalizeCheckout(ref, extra).then((res) => {
      if (res?.status === "paid") {
        setStatus("success");
      } else {
        // Failed/canceled → the shared status page with the right message + game.
        navigate(buildLocalizedPath(lang, "/oops?reason=payment_failed"), { replace: true });
      }
    });
  }, [ref, params, navigate, lang]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--bg))] px-4">
      <div className="w-full max-w-md rounded-2xl border border-line bg-surface/70 p-8 text-center backdrop-blur-md">
        {status === "verifying" && (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-accent" />
            <p className="mt-4 text-body-sm text-content-muted">{t("return.verifying")}</p>
          </>
        )}
        {status === "success" && (
          <>
            <CheckCircle2 className="mx-auto h-10 w-10 text-accent" />
            <h1 className="mt-4 text-h4 font-semibold">{t("return.success")}</h1>
          </>
        )}
        {status === "failed" && (
          <>
            <XCircle className="mx-auto h-10 w-10 text-loss" />
            <h1 className="mt-4 text-h4 font-semibold">{t("return.failed")}</h1>
          </>
        )}
        {status !== "verifying" && (
          <button
            onClick={() => navigate(buildLocalizedPath(lang, "/dashboard"))}
            className="mt-6 inline-flex items-center justify-center rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-glow transition hover:opacity-90"
          >
            {t("return.back")}
          </button>
        )}
      </div>
    </div>
  );
}
