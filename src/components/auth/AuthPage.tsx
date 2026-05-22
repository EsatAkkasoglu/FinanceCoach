import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { login, register, loginWithGoogle, loginDemo } from "@/lib/api";
import { useAuthStore } from "@/store";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import { getLanguageFromPath, buildLocalizedPath } from "@/lib/routing";

type Mode = "login" | "register";

interface AuthPageProps {
  initialMode?: Mode;
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
  const setUser = useAuthStore((s) => s.setUser);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const fn = mode === "login" ? login : register;
      const user = await fn(email.trim(), password);
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
    setGoogleLoading(true);
    try {
      const user = await loginWithGoogle();
      setUser(user);
      toast.success(`Welcome, ${user.name || user.username}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Google sign-in failed";
      toast.error(msg);
    } finally {
      setGoogleLoading(false);
    }
  }

  async function handleDemo() {
    if (demoLoading) return;
    setDemoLoading(true);
    try {
      const user = await loginDemo();
      setUser(user);
      toast.success("Demo hesabına giriş yapıldı. İyi keşifler!");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Demo girişi başarısız";
      toast.error(msg);
    } finally {
      setDemoLoading(false);
    }
  }

  const isRegister = mode === "register";

  return (
    <div className="flex h-screen items-center justify-center bg-bg text-content">
      <div className="w-full max-w-sm rounded-xl border border-line bg-surface p-8 shadow-lg">
        <h1 className="mb-1 text-2xl font-semibold">FinCoach</h1>
        <p className="mb-6 text-sm text-content-muted">
          {isRegister ? t("createAccount") : t("signInToContinue")}
        </p>

        {/* Google Sign-In */}
        <button
          type="button"
          onClick={handleGoogle}
          disabled={googleLoading || submitting}
          className="mb-4 flex w-full items-center justify-center gap-2.5 rounded-md border border-line bg-bg px-4 py-2 text-sm font-medium transition hover:bg-surface-raised disabled:opacity-50"
        >
          <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          {googleLoading ? t("pleaseWait") : t("continueWithGoogle", { defaultValue: "Continue with Google" })}
        </button>

        <div className="relative mb-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-line" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-surface px-2 text-content-muted">or</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-content-muted">
              {t("email", { defaultValue: "Email" })}
            </span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-content-muted">
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
              className="w-full rounded-md border border-line bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </label>

          <button
            type="submit"
            disabled={submitting || googleLoading}
            className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg transition hover:opacity-90 disabled:opacity-50"
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
          className="mt-4 w-full text-center text-xs text-content-muted hover:text-content"
        >
          {isRegister ? t("alreadyHaveAccount") : t("needAccount")}
        </button>

        <div className="mt-6 border-t border-line pt-5">
          <p className="mb-3 text-center text-[11px] text-content-muted">
            <Trans
              t={t}
              i18nKey="demoSectionLabel"
              components={{
                highlight: (
                  <span className="font-bold text-accent" />
                ),
              }}
            />
          </p>
          <button
            type="button"
            onClick={handleDemo}
            disabled={demoLoading || submitting || googleLoading}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-accent/40 bg-accent/10 px-4 py-2.5 text-sm font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {demoLoading ? t("demoLoading") : t("demoBtn")}
          </button>
          <p className="mt-2 text-center text-[10px] text-content-muted">
            {t("demoSectionDesc")}
          </p>
        </div>
      </div>
    </div>
  );
}
