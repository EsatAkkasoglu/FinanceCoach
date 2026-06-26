import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Menu, Globe, LayoutDashboard, Briefcase, Wallet, Coins, Compass, Target, FileText, Settings as SettingsIcon, MessageSquare } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { onIdTokenChanged } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { Sidebar } from "@/components/Sidebar";
import { MobileBottomNav } from "@/components/MobileBottomNav";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Portfolio } from "@/components/portfolio/Portfolio";
import { Budget } from "@/components/budget/Budget";
import { Funds } from "@/components/funds/Funds";
import { Goals } from "@/components/goals/Goals";
import { Discover } from "@/components/insights/Discover";
import { Documents } from "@/components/documents/Documents";
import { Settings } from "@/components/settings/Settings";
import { CurrencySwitcher } from "@/components/budget/CurrencySwitcher";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { AuthPage } from "@/components/auth/AuthPage";
import { LandingPage } from "@/components/landing/LandingPage";
import { LegalPage } from "@/components/legal/LegalPage";
import { DemoTour, TourReplayButton } from "@/components/tour/DemoTour";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useAuthStore, useConversationStore, useUserStore, useTourStore } from "@/store";
import { buildLocalizedPath, getLanguageFromPath, isSupportedLanguage, stripLanguagePrefix } from "@/lib/routing";
import {
  ping,
  createConversation,
  fetchMe,
  handleGoogleRedirectResult,
  recordConsent,
  PENDING_CONSENT_KEY,
  getProfile,
  onUnauthorized,
  DEMO_TOKEN_KEY,
  type Conversation,
} from "@/lib/api";
import { toast } from "sonner";

// Ambient WebGL backdrop is code-split so it never blocks the app's first paint.
const AmbientField3D = lazy(() => import("@/components/three/AmbientField3D"));

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

  // No convId in URL → reuse an existing empty (untitled) conversation if one
  // exists, otherwise create one. Prevents a new "Untitled" conversation from
  // being spawned every time the user opens Coach without sending a message.
  useEffect(() => {
    if (convId || creating) return;
    const existingEmpty = conversations.find((c) => !c.title);
    if (existingEmpty) {
      navigate(buildLocalizedPath(currentLanguage, `/chat/${existingEmpty.id}`), { replace: true });
      return;
    }
    setCreating(true);
    createConversation()
      .then((c) => {
        addConversation(c);
        navigate(buildLocalizedPath(currentLanguage, `/chat/${c.id}`), { replace: true });
      })
      .catch(() => {})
      .finally(() => setCreating(false));
  }, [convId, creating, conversations, addConversation, navigate, currentLanguage]);

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
  const reduceMotion = useReducedMotion();
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const { user, ready, setUser, setReady } = useAuthStore();
  const navigate = useNavigate();
  const { activeConversationId, conversations } = useConversationStore();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const { seen: tourSeen, active: tourActive, start: startTour } = useTourStore();
  const location = useLocation();
  const currentLanguage = getLanguageFromPath(location.pathname);
  const appPath = stripLanguagePrefix(location.pathname);
  const activeLanguage = currentLanguage ?? (isSupportedLanguage(i18n.language) ? i18n.language : "en");
  useEffect(() => { setMobileNavOpen(false); }, [location.pathname]);

  // Sidebar collapsed state — lifted here so main content can sync its margin
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem("sidebar_collapsed") === "true"; } catch { return false; }
  });
  function toggleSidebarCollapsed() {
    setSidebarCollapsed((v) => {
      const next = !v;
      try { localStorage.setItem("sidebar_collapsed", String(next)); } catch {}
      return next;
    });
  }

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

  // Health check with quiet retry: a transient blip stays in the "reconnecting"
  // (amber) state and silently retries, only flipping to red "offline" + toast
  // after several sustained failures — so the demo never flashes a scary red.
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function check() {
      try {
        const r = await ping();
        if (cancelled) return;
        setHealthy(true);
        if (r.demo_mode) toast.info(t("errors.demoMode"));
      } catch {
        if (cancelled) return;
        attempts += 1;
        setHealthy(attempts >= 3 ? false : null); // amber while reconnecting
        if (attempts === 3) toast.error(t("errors.backendUnreachable"));
        timer = setTimeout(check, attempts < 3 ? 2000 : 10000);
      }
    }
    void check();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Restore session via Firebase auth state — fires immediately on mount.
  useEffect(() => {
    // Handle Google redirect result first (prod sign-in flow)
    handleGoogleRedirectResult()
      .then((u) => {
        if (!u) return;
        setUser(u);
        // A register-mode Google redirect left a flag — record KVKK consent now.
        if (sessionStorage.getItem(PENDING_CONSENT_KEY)) {
          sessionStorage.removeItem(PENDING_CONSENT_KEY);
          void recordConsent().catch(() => undefined);
        }
      })
      .catch(() => {});

    // onIdTokenChanged fires on login, logout AND silent token refresh (~1 hr).
    // This keeps the local user state in sync without showing "session expired".
    return onIdTokenChanged(auth, async (firebaseUser) => {
      // Cap the initial session restore at 8 s so a Cloud Run cold start
      // doesn't leave the app stuck on the loading splash for 25+ seconds.
      // After the cap, ready=true fires and the user sees the login page.
      let timedOut = false;
      const earlyReady = setTimeout(() => {
        timedOut = true;
        setReady(true);
      }, 8_000);

      try {
        if (firebaseUser) {
          const u = await fetchMe();
          // if fetchMe fails (backend unreachable), keep the existing user state
          // rather than logging out — the user is still authenticated with Firebase
          if (!timedOut && u) setUser(u);
        } else if (localStorage.getItem(DEMO_TOKEN_KEY)) {
          // Demo login: no Firebase user but we have a backend JWT
          const u = await fetchMe();
          if (!timedOut) {
            if (u) {
              setUser(u);
            } else {
              localStorage.removeItem(DEMO_TOKEN_KEY);
              setUser(null);
            }
          }
        } else {
          if (!timedOut) setUser(null);
        }
      } catch {
        // fetchMe threw (network error, timeout, etc.) — keep existing auth state
        // and still mark as ready so the UI doesn't hang on the loading screen.
      } finally {
        clearTimeout(earlyReady);
        if (!timedOut) setReady(true);
        timedOut = true;
      }
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

  // Auto-start tour for first-time visitors (once per browser)
  useEffect(() => {
    if (user && user.has_onboarded && !tourSeen && !tourActive) {
      const timer = setTimeout(startTour, 800);
      return () => clearTimeout(timer);
    }
  }, [user?.id, user?.has_onboarded]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSelectConversation(conv: Conversation) {
    navigate(buildLocalizedPath(activeLanguage, `/chat/${conv.id}`));
  }

  function handleNewChatMobile() {
    if (activeConversationId) {
      navigate(buildLocalizedPath(activeLanguage, `/chat/${activeConversationId}`));
    } else {
      navigate(buildLocalizedPath(activeLanguage, "/chat"));
    }
  }

  function handleLanguageChange(language: "en" | "tr") {
    void i18n.changeLanguage(language);
    navigate(buildLocalizedPath(language, location.pathname), { replace: true });
    setLangOpen(false);
  }

  if (!currentLanguage) {
    return <PrefixedDashboardRedirect language={activeLanguage} />;
  }

  // Language + tour controls. Two placements:
  //  - "fab": fixed bottom-right pill, for screens with no header (login/onboarding).
  //  - "header": inline cluster inside the top bar, so it never collides with the
  //    chat composer's send button in the bottom-right corner of the main app.
  const renderLanguageControls = (variant: "fab" | "header") => (
    <div
      className={
        variant === "fab"
          ? "fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2"
          : "relative flex items-center gap-3"
      }
    >
      {langOpen && (
        <div
          className={`flex flex-col gap-1.5 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2 shadow-xl ${
            variant === "header" ? "absolute right-0 top-full z-50 mt-2" : ""
          }`}
        >
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
      {user && user.has_onboarded && <TourReplayButton />}
      <button
        onClick={() => setLangOpen((v) => !v)}
        className={
          variant === "fab"
            ? "flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white shadow-lg transition hover:bg-accent/90 active:scale-95"
            : "flex h-8 w-8 items-center justify-center rounded-lg text-[hsl(var(--text-muted))] transition hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
        }
        title={t("language")}
      >
        <Globe className="h-4 w-4" />
      </button>
    </div>
  );
  const languageSwitcher = renderLanguageControls("fab");

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-[hsl(var(--bg))] text-sm text-[hsl(var(--text-muted))]">
        {t("loading")}
      </div>
    );
  }
  if (!user) {
    const appPathForAuth = stripLanguagePrefix(location.pathname);
    const isRegisterPath = appPathForAuth === "/register";
    const isAuthPath = appPathForAuth === "/login" || appPathForAuth === "/register";
    // Legal pages are public — reachable from the marketing footer while logged out.
    if (appPathForAuth.startsWith("/legal/") || appPathForAuth === "/legal") {
      return (
        <>
          <LegalPage />
          {languageSwitcher}
        </>
      );
    }
    if (isAuthPath) {
      return (
        <>
          <AuthPage initialMode={isRegisterPath ? "register" : "login"} />
          {languageSwitcher}
        </>
      );
    }
    // Logged-out visitors get the marketing landing page. Normalize to the
    // clean language-root URL (/en, /tr) so it isn't served at /dashboard etc.
    if (appPathForAuth !== "/") {
      return <Navigate to={`/${activeLanguage}`} replace />;
    }
    return <LandingPage />;
  }
  if (!user.has_onboarded) {
    return (
      <>
        <OnboardingWizard />
        {languageSwitcher}
      </>
    );
  }

  // Page meta for header title + icon — titles resolved at render time with proper t() keys
  const PAGE_META: Record<string, { title: string; icon: React.ElementType }> = {
    "/dashboard": { title: t("nav.dashboard"), icon: LayoutDashboard },
    "/portfolio":  { title: t("nav.portfolio"), icon: Briefcase      },
    "/budget":     { title: t("nav.budget"),    icon: Wallet         },
    "/funds":      { title: t("nav.funds"),     icon: Coins          },
    "/discover":   { title: t("nav.discover"),  icon: Compass        },
    "/goals":      { title: t("nav.goals"),     icon: Target         },
    "/documents":  { title: t("nav.documents"), icon: FileText       },
    "/settings":   { title: t("nav.settings"),  icon: SettingsIcon   },
    "/chat":       { title: t("nav.coach"),     icon: MessageSquare  },
  };
  const matchedMeta = Object.entries(PAGE_META).find(([k]) => appPath === k || appPath.startsWith(k + "/"));
  const pageMeta = matchedMeta?.[1] ?? null;

  // Chat breadcrumb: show conversation title when on a chat route
  const onChatRoute = appPath.startsWith("/chat");
  const activeConv = onChatRoute
    ? conversations.find((c) => c.id === activeConversationId) ?? null
    : null;

  // CurrencySwitcher only on financial pages where currency matters
  const CURRENCY_PAGES = ["/dashboard", "/portfolio", "/budget", "/funds", "/goals"];
  const showCurrency = CURRENCY_PAGES.some((p) => appPath === p || appPath.startsWith(p + "/"));

  // Key for page transitions — top-level segment only so /chat/abc ↔ /chat/def doesn't re-animate
  const transitionKey = appPath.split("/")[1] ?? "home";

  return (
    <div className="relative isolate flex h-screen bg-[hsl(var(--bg))] text-[hsl(var(--text))]">
      {/* Ambient backdrop: static radial glows + drifting WebGL motes.
          -z-10 inside the isolated root so every page (and the glass header/
          sidebar) floats above it. */}
      <div className="app-glow pointer-events-none absolute inset-0 -z-10" aria-hidden="true">
        {!reduceMotion && (
          <ErrorBoundary fallback={null}>
            <Suspense fallback={null}>
              <AmbientField3D />
            </Suspense>
          </ErrorBoundary>
        )}
      </div>

      <DemoTour />

      <Sidebar
        healthy={healthy}
        onSelectConversation={handleSelectConversation}
        activeConvId={activeConversationId}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebarCollapsed}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* ── Top header bar ── */}
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[hsl(var(--border))]/60 bg-[hsl(var(--surface))]/60 px-4 backdrop-blur-xl md:px-5">
          {/* Mobile: hamburger */}
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="rounded-lg p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))] md:hidden"
            aria-label={t("openNav")}
          >
            <Menu className="h-5 w-5" />
          </button>

          {/* Page title / breadcrumb — desktop */}
          <div className="hidden md:flex items-center gap-2 min-w-0">
            {pageMeta && (() => {
              const Icon = pageMeta.icon;
              return (
                <>
                  <Icon className="h-4 w-4 shrink-0 text-accent/60" />
                  <span className="text-sm font-semibold tracking-tight truncate">
                    {onChatRoute && activeConv?.title ? activeConv.title : pageMeta.title}
                  </span>
                </>
              );
            })()}
          </div>

          {/* Mobile: app name */}
          <span className="text-sm font-semibold tracking-tight md:hidden">{t("appName")}</span>

          {/* Right side */}
          <div className="ml-auto flex items-center gap-3">
            {/* Backend health indicator */}
            <span
              className={`hidden md:block h-2 w-2 rounded-full shrink-0 ${healthy === null ? "animate-pulse" : ""}`}
              style={{
                backgroundColor: healthy === true ? "#22c55e" : healthy === false ? "#ef4444" : "#f59e0b",
                boxShadow: healthy === true ? "0 0 6px rgba(34,197,94,0.6)" : undefined,
              }}
              title={healthy === true ? "Backend online" : healthy === false ? "Backend offline" : "Reconnecting…"}
            />
            {/* Only show currency switcher on financial pages — compact dropdown */}
            {showCurrency && <CurrencySwitcher variant="compact" />}
            {/* Proactive news alerts — polls + popover with "ask the coach" CTA */}
            <NotificationBell />
            {/* Language + tour controls — inline so they don't overlap the chat send button */}
            {renderLanguageControls("header")}
          </div>
        </header>

        {/* ── Page content with transitions ── */}
        <AnimatePresence mode="wait">
          <motion.main
            key={transitionKey}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className={
              onChatRoute
                ? "min-h-0 flex-1 overflow-hidden"
                : "flex-1 overflow-y-auto px-4 pb-24 pt-6 md:px-8 md:pb-12 md:pt-10"
            }
          >
            <div className={onChatRoute ? "mx-auto h-full w-full max-w-4xl px-4 pt-4 pb-3 md:px-6" : "mx-auto w-full max-w-5xl"}>
            <ErrorBoundary>
            <Routes location={location}>
              <Route path="/" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
              <Route path="/:lang/dashboard" element={<Dashboard />} />
              <Route path="/:lang/portfolio" element={<Portfolio />} />
              <Route path="/:lang/budget" element={<Budget />} />
              <Route path="/:lang/funds" element={<Funds />} />
              <Route path="/:lang/settings" element={<Settings />} />
              <Route path="/:lang/goals" element={<Goals />} />
              <Route path="/:lang/discover" element={<Discover />} />
              <Route path="/:lang/documents" element={<Documents />} />
              <Route path="/:lang/chat" element={<ChatRoute />} />
              <Route path="/:lang/chat/:convId" element={<ChatRoute />} />
              <Route path="/:lang/legal/:doc" element={<LegalPage />} />
              <Route path="/:lang" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
              <Route path="/:lang/*" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
              <Route path="*" element={<PrefixedDashboardRedirect language={activeLanguage} />} />
            </Routes>
            </ErrorBoundary>
            </div>
          </motion.main>
        </AnimatePresence>

        {/* Mobile bottom tab bar */}
        <MobileBottomNav onChatPress={() => handleNewChatMobile()} />
      </div>
    </div>
  );
}
