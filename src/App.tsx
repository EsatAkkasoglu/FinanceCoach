import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
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
import {
  ping,
  createConversation,
  fetchMe,
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
          <span className="font-semibold capitalize">{name}</span> view —
          placeholder. Implementation coming next.
        </p>
      </div>
    </div>
  );
}

function ChatRoute() {
  const { convId } = useParams<{ convId: string }>();
  const navigate = useNavigate();
  const { conversations, setActive, addConversation } = useConversationStore();
  const conv = conversations.find((c) => c.id === convId) ?? null;
  const [creating, setCreating] = useState(false);

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
        navigate(`/chat/${c.id}`, { replace: true });
      })
      .catch(() => {})
      .finally(() => setCreating(false));
  }, [convId, creating, addConversation, navigate]);

  if (!convId) {
    return (
      <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
        <div className="card-muted text-sm">Starting a new conversation…</div>
      </div>
    );
  }
  if (!conv) {
    return (
      <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
        <div className="card-muted text-sm">
          Conversation not found. Pick one from the sidebar or start a{" "}
          <span className="font-semibold text-accent">New chat</span>.
        </div>
      </div>
    );
  }
  return <ChatPanel convId={conv.id} threadId={conv.thread_id} />;
}

export default function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const { user, ready, setUser, setReady } = useAuthStore();
  const navigate = useNavigate();
  const { activeConversationId } = useConversationStore();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => { setMobileNavOpen(false); }, [location.pathname]);

  useEffect(() => {
    ping()
      .then((r) => {
        setHealthy(true);
        if (r.demo_mode) toast.info("Demo mode is on — using cached responses");
      })
      .catch(() => {
        setHealthy(false);
        toast.error("Backend not reachable. Start it with `uv run uvicorn app.main:app`.");
      });
  }, []);

  // Restore session from stored token on first mount.
  useEffect(() => {
    fetchMe()
      .then((u) => setUser(u))
      .finally(() => setReady(true));
  }, [setUser, setReady]);

  // If any API call returns 401, drop the user back to the login screen.
  useEffect(() => {
    return onUnauthorized(() => {
      setUser(null);
      toast.error("Session expired. Please sign in again.");
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
    navigate(`/chat/${conv.id}`);
  }

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-[hsl(var(--bg))] text-sm text-[hsl(var(--text-muted))]">
        Loading…
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
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold tracking-tight md:hidden">FinCoach</span>
          <div className="ml-auto">
            <CurrencySwitcher />
          </div>
        </div>
      <main className="flex-1 overflow-y-auto p-4 md:p-8">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/budget" element={<Budget />} />
          <Route path="/funds" element={<Funds />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/goals" element={<Goals />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/documents" element={<PlaceholderView name="documents" />} />
          <Route path="/chat" element={<ChatRoute />} />
          <Route path="/chat/:convId" element={<ChatRoute />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
      </div>
    </div>
  );
}
