import { useState } from "react";
import { login, register } from "@/lib/api";
import { useAuthStore } from "@/store";
import { toast } from "sonner";
import { KeyRound } from "lucide-react";

type Mode = "login" | "register";

const TEST_USERNAME = "testUser";
const TEST_PASSWORD = "TestUser123!";

export function AuthPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const fn = mode === "login" ? login : register;
      const { user } = await fn(username.trim(), password);
      setUser(user);
      toast.success(mode === "login" ? `Welcome back, ${user.username}` : "Account created");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const isRegister = mode === "register";

  function useTestAccount() {
    setMode("login");
    setUsername(TEST_USERNAME);
    setPassword(TEST_PASSWORD);
  }

  return (
    <div className="flex h-screen items-center justify-center bg-[hsl(var(--bg))] text-[hsl(var(--text))]">
      <div className="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-8 shadow-lg">
        <h1 className="mb-1 text-2xl font-semibold">FinCoach</h1>
        <p className="mb-6 text-sm text-[hsl(var(--text-muted))]">
          {isRegister ? "Create your account" : "Sign in to continue"}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[hsl(var(--text-muted))]">
              Username
            </span>
            <input
              type="text"
              autoComplete="username"
              required
              minLength={3}
              maxLength={32}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-2 text-sm outline-none focus:border-[hsl(var(--accent))]"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[hsl(var(--text-muted))]">
              Password
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
            disabled={submitting}
            className="w-full rounded-md bg-[hsl(var(--accent))] px-4 py-2 text-sm font-medium text-[hsl(var(--accent-fg))] transition hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
          </button>
        </form>

        {!isRegister && (
          <div className="mt-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-3">
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-muted text-accent">
                <KeyRound className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium">Want to try it first?</p>
                <p className="mt-0.5 text-[11px] leading-4 text-[hsl(var(--text-muted))]">
                  Use the test account to explore the app with sample data.
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <code className="rounded bg-[hsl(var(--bg))] px-1.5 py-1 text-[11px] text-[hsl(var(--text-muted))]">
                    {TEST_USERNAME}
                  </code>
                  <button
                    type="button"
                    onClick={useTestAccount}
                    className="rounded-md bg-[hsl(var(--bg))] px-2 py-1 text-[11px] font-medium text-[hsl(var(--text))] transition hover:bg-accent hover:text-white"
                  >
                    Use test account
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={() => setMode(isRegister ? "login" : "register")}
          className="mt-4 w-full text-center text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
        >
          {isRegister ? "Already have an account? Sign in" : "Need an account? Register"}
        </button>
      </div>
    </div>
  );
}
