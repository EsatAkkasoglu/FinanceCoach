import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Menu, Globe } from "lucide-react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { onAuthStateChanged, onIdTokenChanged } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Portfolio } from "@/components/portfolio/Portfolio";
import { Budget } from "@/components/budget/Budget";
import { Funds } from "@/components/funds/Funds";
import { Goals } from "@/components/goals/Goals";
import { Discover } from "@/components/insights/Discover";
import { Settings } from "@/components/settings/Settings";
import { CurrencySwitcher } from "@/components/budget/CurrencySwitcher";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { AuthPage } from "@/components/auth/AuthPage";
import { useAuthStore, useConversationStore, useUserStore } from "@/store";
import { buildLocalizedPath, getLanguageFromPath, isSupportedLanguage, stripLanguagePrefix } from "@/lib/routing";
import {
  ping,
  createConversation,
  fetchMe,
  handleGoogleRedirectResult,
  getProfile,
  onUnauthorized,
  type Conversation,
} from "@/lib/api";
import { toast } from "sonner";

function PlaceholderView({ name }: { name: string }) {
  return (
    <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
      <div className="card-muted">
        <p className="text-sm">
          <span className="font-semibold capitalize">{name}</span>
        </p>
      </div>
    </div>
  );
}

function ChatRoute() {
  const { t } = useTranslation("chat");
  const { convId } = useParams<{ convId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { conversations, setActive, addConversation } = useConversationStore();
  const conv = conversations.find((c) => c.id === convId) ?? null;
  const [creating, setCreating] = useState(false);
  const currentLanguage = getLanguageFromPath(location.pathname) ?? "en";

  useEffect(() => {
    if (convId) setActive(convId);
  }, [convId, setActive]);

  // No convId in URL → auto-create a conversation and redirect.
  useEffect(() => {
    if (convId || creating) return;
    setCreating(true);
    createConversation()
      .then((c) => {
        addConversation(c);
        navigate(buildLocalizedPath(currentLanguage, `/chat/${c.id}`), { replace: true });
      })
      .catch(() => {})
      .finally(() => setCreating(false));
  }, [convId, creating, addConversation, navigate, currentLanguage]);

  if (!convId) {
    return (
      <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
        <div className="card-muted text-sm">{t("newConversation")}</div>
      </div>
    );
  }
  if (!conv) {
    return (
      <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
        <div className="card-muted text-sm">
          {t("conversationNotFound")}{" "}
          <span className="font-semibold text-accent">{t("newChat")}</span>.
        </div>
      </div>
    );
  }
  return <ChatPanel convId={conv.id} threadId={conv.thread_id} />;
}

function PrefixedDashboardRedirect({ language }: { language: "en" | "tr" }) {
  const location = useLocation();
  const currentLanguage = getLanguageFromPath(location.pathname) ?? language;
  return <Navigate to={`/${currentLanguage}/dashboard`} replace />;
}

const ROUTE_TITLE_KEYS = {
  "/dashboard": "nav.dashboard",
  "/portfolio": "nav.portfolio",
  "/budget":    "nav.budget",
  "/funds":     "nav.funds",
  "/discover":  "nav.discover",
  "/goals":     "nav.goals",
  "/documents": "nav.documents",
  "/settings":  "nav.settings",
} as const;

export default function App() {
  const { t, i18n } = useTranslation();
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const { user, ready, setUser, setReady } = useAuthStore();
  const navigate = useNavigate();
  const { activeConversationId } = useConversationStore();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const location = useLocation();
  const currentLanguage = getLanguageFromPath(location.pathname);
  const appPath = stripLanguagePrefix(location.pathname);
  const activeLanguage = currentLanguage ?? (isSupportedLanguage(i18n.language) ? i18n.language : "en");
  useEffect(() => { setMobileNavOpen(false); }, [location.pathname]);

  useEffect(() => {
    if (currentLanguage && i18n.language !== currentLanguage) {
      void i18n.changeLanguage(currentLanguage);
    }
  }, [currentLanguage, i18n]);

  // Sync browser tab title with current route + language
  useEffect(() => {
    const key = Object.keys(ROUTE_TITLE_KEYS).find((k) => appPath === k || appPath.startsWith(k + "/"));
    const pageLabel = key ? t(ROUTE_TITLE_KEYS[key as keyof typeof ROUTE_TITLE_KEYS]) : t("appName");
    document.title = `${pageLabel} — ${t("appName")}`;
  }, [appPath, i18n.language, t]);

  useEffect(() => {
    ping()
      .then((r) => {
        setHealthy(true);
        if (r.demo_mode) toast.info(t("errors.demoMode"));
      })
      .catch(() => {
        setHealthy(false);
        toast.error(t("errors.backendUnreachable"));
      });
  }, []);

  // Restore session via Firebase auth state — fires immediately on mount.
  useEffect(() => {
    // Handle Google redirect result first (prod sign-in flow)
    handleGoogleRedirectResult()
      .then((u) => { if (u) setUser(u); })
      .catch(() => {});

    // onIdTokenChanged fires on login, logout AND silent token refresh (~1 hr).
    // This keeps the local user state in sync without showing "session expired".
    return onIdTokenChanged(auth, async (firebaseUser) => {
      if (firebaseUser) {
        const u = await fetchMe();
        setUser(u);
      } else {
        setUser(null);
      }
      setReady(true);
    });
  }, [setUser, setReady]);

  // If any API call returns 401, drop the user back to the login screen.
  useEffect(() => {
    return onUnauthorized(() => {
      setUser(null);
      toast.error(t("errors.sessionExpired"));
    });
  }, [setUser]);

  // When the logged-in user changes, sync the profile cache so the dashboard
  // doesn't show the previous user's name/avatar.
  useEffect(() => {
    if (!user) {
      useUserStore.getState().resetOnboarding();
      return;
    }
    if (!user.has_onboarded) return;
    getProfile()
      .then((p) =>
        useUserStore.getState().setProfile({
          name: p.name,
          avatar: p.avatar,
          monthlyIncome: p.monthly_income,
          riskScore: p.risk_score,
          riskProfile: p.risk_profile,
        })
      )
      .catch(() => {});
  }, [user?.id, user?.has_onboarded]);

  function handleSelectConversation(conv: Conversation) {
    navigate(buildLocalizedPath(activeLanguage, `/chat/${conv.id}`));
  }

  function handleLanguageChange(language: "en" | "tr") {
    void i18n.changeLanguage(language);
    navigate(buildLocalizedPath(language, location.pathname), { replace: true });
    setLangOpen(false);
  }

  if (!currentLanguage) {
    return <PrefixedDashboardRedirect language={activeLanguage} />;
  }

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-[hsl(var(--bg))] text-sm text-[hsl(var(--text-muted))]">
        {t("loading")}
      </div>
    );
  }
  if (!user) {
    return <AuthPage />;
  }
  if (!user.has_onboarded) {
    return <OnboardingWizard />;
  }

  return (
    <div className="flex h-screen bg-[hsl(var(--bg))] text-[hsl(var(--text))]">
      {/* Floating language switcher */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
        {langOpen && (
          <div className="flex flex-col gap-1.5 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2 shadow-xl">
            {(["tr", "en"] as const).map((lang) => (
              <button
                key={lang}
                onClick={() => handleLanguageChange(lang)}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  i18n.language === lang
                    ? "bg-accent text-white"
                    : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
                }`}
              >
                <span className="text-base leading-none">{lang === "tr" ? "🇹🇷" : "🇬🇧"}</span>
                {t(lang === "tr" ? "languageTr" : "languageEn")}
              </button>
            ))}
          </div>
        )}
        <button
          onClick={() => setLangOpen((v) => !v)}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white shadow-lg transition hover:bg-accent/90 active:scale-95"
          title={t("language")}
        >
          <Globe className="h-4 w-4" />
        </button>
      </div>

      <Sidebar
        healthy={healthy}
        onSelectConversation={handleSelectConversation}
        activeConvId={activeConversationId}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3 md:px-6">
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="rounded-lg p-2 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))] md:hidden"
            aria-label={t("openNav")}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold tracking-tight md:hidden">{t("appName")}</span>
          <div className="ml-auto">
            <CurrencySwitcher />
          </div>
        </div>
      <main className="flex-1 overflow-y-auto p-4 md:p-8">
        <Routes>
          <Route path="/" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
          <Route path="/:lang/dashboard" element={<Dashboard />} />
          <Route path="/:lang/portfolio" element={<Portfolio />} />
          <Route path="/:lang/budget" element={<Budget />} />
          <Route path="/:lang/funds" element={<Funds />} />
          <Route path="/:lang/settings" element={<Settings />} />
          <Route path="/:lang/goals" element={<Goals />} />
          <Route path="/:lang/discover" element={<Discover />} />
          <Route path="/:lang/documents" element={<PlaceholderView name="documents" />} />
          <Route path="/:lang/chat" element={<ChatRoute />} />
          <Route path="/:lang/chat/:convId" element={<ChatRoute />} />
          <Route path="/:lang" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
          <Route path="/:lang/*" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
          <Route path="*" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
        </Routes>
      </main>
      </div>
    </div>
  );
}
