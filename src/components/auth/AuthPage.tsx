import { useState } from "react";
import { useTranslation } from "react-i18next";
import { login, register, loginWithGoogle } from "@/lib/api";
import { useAuthStore } from "@/store";
import { toast } from "sonner";

type Mode = "login" | "register";

export function AuthPage() {
  const { t } = useTranslation("auth");
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
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

  const isRegister = mode === "register";

  return (
    <div className="flex h-screen items-center justify-center bg-[hsl(var(--bg))] text-[hsl(var(--text))]">
      <div className="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-8 shadow-lg">
        <h1 className="mb-1 text-2xl font-semibold">FinCoach</h1>
        <p className="mb-6 text-sm text-[hsl(var(--text-muted))]">
          {isRegister ? t("createAccount") : t("signInToContinue")}
        </p>

        {/* Google Sign-In */}
        <button
          type="button"
          onClick={handleGoogle}
          disabled={googleLoading || submitting}
          className="mb-4 flex w-full items-center justify-center gap-2.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-4 py-2 text-sm font-medium transition hover:bg-[hsl(var(--surface-2))] disabled:opacity-50"
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
            <div className="w-full border-t border-[hsl(var(--border))]" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-[hsl(var(--surface))] px-2 text-[hsl(var(--text-muted))]">or</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[hsl(var(--text-muted))]">
              {t("email", { defaultValue: "Email" })}
            </span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--accent))]"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[hsl(var(--text-muted))]">
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
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--accent))]"
            />
          </label>

          <button
            type="submit"
            disabled={submitting || googleLoading}
            className="w-full rounded-md bg-[hsl(var(--accent))] px-4 py-2 text-sm font-medium text-[hsl(var(--accent-fg))] transition hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? t("pleaseWait") : isRegister ? t("createAccountBtn") : t("signIn")}
          </button>
        </form>

        <button
          type="button"
          onClick={() => setMode(isRegister ? "login" : "register")}
          className="mt-4 w-full text-center text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
        >
          {isRegister ? t("alreadyHaveAccount") : t("needAccount")}
        </button>
      </div>
    </div>
  );
}
