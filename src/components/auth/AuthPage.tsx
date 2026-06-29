import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { login, register, loginWithGoogle, loginDemo, recordConsent, PENDING_CONSENT_KEY } from "@/lib/api";
import { useAuthStore } from "@/store";
import { toast } from "sonner";
import { Sparkles, ArrowRight } from "lucide-react";
import { getLanguageFromPath, buildLocalizedPath } from "@/lib/routing";

type Mode = "login" | "register";

interface AuthPageProps {
  initialMode?: Mode;
}

function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <g stroke="#FFFFFF" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 50 L20 16 L42 16 L52 6" />
        <path d="M46 6 L52 6 L52 12" />
        <path d="M20 32 L36 32" />
      </g>
    </svg>
  );
}

export function AuthPage({ initialMode = "login" }: AuthPageProps) {
  const { t } = useTranslation("auth");
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoStatusMsg, setDemoStatusMsg] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);

  const busy = submitting || googleLoading || demoLoading;
  const lang = getLanguageFromPath(location.pathname) ?? "en";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    if (mode === "register" && !consent) {
      toast.error(t("consentRequired"));
      return;
    }
    setSubmitting(true);
    try {
      const fn = mode === "login" ? login : register;
      const user = await fn(email.trim(), password);
      // Record KVKK/Terms consent server-side (the box is required to get here).
      if (mode === "register") await recordConsent().catch(() => undefined);
      setUser(user);
      toast.success(mode === "login" ? `Welcome back, ${user.username}` : "Account created");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogle() {
    if (googleLoading) return;
    if (mode === "register" && !consent) {
      toast.error(t("consentRequired"));
      return;
    }
    setGoogleLoading(true);
    // In prod, loginWithGoogle redirects (page reload) and the lines below never
    // run — leave a flag so App.tsx records consent when the redirect returns.
    if (mode === "register") sessionStorage.setItem(PENDING_CONSENT_KEY, "1");
    try {
      const user = await loginWithGoogle();
      if (mode === "register") {
        await recordConsent().catch(() => undefined);
        sessionStorage.removeItem(PENDING_CONSENT_KEY);
      }
      setUser(user);
      toast.success(`Welcome, ${user.name || user.username}`);
    } catch (err) {
      sessionStorage.removeItem(PENDING_CONSENT_KEY);  // attempt failed — don't carry it over
      const msg = err instanceof Error ? err.message : "Google sign-in failed";
      toast.error(msg);
    } finally {
      setGoogleLoading(false);
    }
  }

  async function handleDemo() {
    if (demoLoading) return;
    setDemoLoading(true);
    setDemoStatusMsg(null);

    // Show "server warming up" hint after 6 s — Cloud Run cold starts take 30-90 s.
    const warmupHint = setTimeout(() => {
      setDemoStatusMsg(t("demoServerWarming", { defaultValue: "Sunucu hazırlanıyor, lütfen bekleyin..." }));
    }, 6_000);

    try {
      const user = await loginDemo();
      setUser(user);
      toast.success("Demo hesabına giriş yapıldı. İyi keşifler!");
    } catch (err) {
      const isNetwork =
        err instanceof TypeError ||
        (err instanceof DOMException &&
          (err.name === "TimeoutError" || err.name === "AbortError"));
      const msg = isNetwork
        ? t("demoServerBusy", {
            defaultValue: "Sunucu başlatılıyor, lütfen birkaç saniye sonra tekrar deneyin.",
          })
        : err instanceof Error
          ? err.message
          : "Demo girişi başarısız";
      toast.error(msg);
    } finally {
      clearTimeout(warmupHint);
      setDemoLoading(false);
      setDemoStatusMsg(null);
    }
  }

  const isRegister = mode === "register";

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-bg px-4 text-content">
      {/* Ambient accent glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-[28rem] w-[28rem] -translate-x-1/2 rounded-full bg-accent/20 blur-[120px]"
      />

      <div className="relative w-full max-w-sm">
        {/* Brand + value proposition */}
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent shadow-glow">
            <BrandMark />
          </div>
          <h1 className="text-h2 font-bold tracking-tight">{t("appName", { ns: "common", defaultValue: "FinCoach" })}</h1>
          <p className="mt-2 max-w-xs text-body-sm text-content-muted">{t("tagline")}</p>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-6 shadow-2xl">
          {/* Primary action — demo (the fastest path to value) */}
          <p className="mb-2 text-center text-overline uppercase text-content-muted">
            <Trans t={t} i18nKey="demoSectionLabel" components={{ highlight: <span className="font-bold text-accent" /> }} />
          </p>
          <button
            type="button"
            onClick={handleDemo}
            disabled={busy}
            className="group flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-accent-fg shadow-glow transition hover:bg-accent/90 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {demoLoading ? t("demoLoading") : t("demoPrimary")}
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          {demoStatusMsg ? (
            <p className="mt-2 text-center text-caption text-amber-400">{demoStatusMsg}</p>
          ) : (
            <p className="mt-2 text-center text-caption text-content-muted">{t("demoReassure")}</p>
          )}

          {/* Divider */}
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-line" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-surface px-3 text-caption text-content-muted">{t("orSignIn")}</span>
            </div>
          </div>

          {/* Google */}
          <button
            type="button"
            onClick={handleGoogle}
            disabled={busy}
            className="mb-4 flex w-full items-center justify-center gap-2.5 rounded-lg border border-line bg-bg px-4 py-2.5 text-sm font-medium transition hover:bg-surface-raised disabled:opacity-50"
          >
            <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            {googleLoading ? t("pleaseWait") : t("continueWithGoogle", { defaultValue: "Continue with Google" })}
          </button>

          {/* Email / password */}
          <form onSubmit={handleSubmit} className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-caption font-medium text-content-muted">
                {t("email", { defaultValue: "Email" })}
              </span>
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/40"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-caption font-medium text-content-muted">
                {t("password")}
              </span>
              <input
                type="password"
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
                minLength={6}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/40"
              />
            </label>

            {isRegister && (
              <label className="flex items-start gap-2.5 pt-1 text-caption text-content-muted">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-line text-accent accent-accent focus:ring-1 focus:ring-accent/40"
                />
                <span>
                  <Trans
                    t={t}
                    i18nKey="consent"
                    components={{
                      terms: (
                        <a
                          href={buildLocalizedPath(lang, "/legal/terms")}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-accent underline-offset-2 hover:underline"
                        />
                      ),
                      privacy: (
                        <a
                          href={buildLocalizedPath(lang, "/legal/privacy")}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-accent underline-offset-2 hover:underline"
                        />
                      ),
                    }}
                  />
                </span>
              </label>
            )}

            <button
              type="submit"
              disabled={busy || (isRegister && !consent)}
              className="w-full rounded-lg border border-line bg-surface-raised px-4 py-2.5 text-sm font-medium transition hover:border-content-muted disabled:opacity-50"
            >
              {submitting ? t("pleaseWait") : isRegister ? t("createAccountBtn") : t("signIn")}
            </button>
          </form>

          <button
            type="button"
            onClick={() => {
              const next: Mode = isRegister ? "login" : "register";
              setMode(next);
              const lang = getLanguageFromPath(location.pathname) ?? "en";
              navigate(buildLocalizedPath(lang, `/${next}`), { replace: true });
            }}
            className="mt-4 w-full text-center text-caption text-content-muted transition hover:text-content"
          >
            {isRegister ? t("alreadyHaveAccount") : t("needAccount")}
          </button>
        </div>
      </div>
    </div>
  );
}
