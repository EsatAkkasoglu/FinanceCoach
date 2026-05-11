import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { Portfolio } from "@/components/portfolio/Portfolio";
import { Budget } from "@/components/budget/Budget";
import { Settings } from "@/components/settings/Settings";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { useUserStore, useConversationStore } from "@/store";
import { ping, createConversation, type Conversation } from "@/lib/api";
import { toast } from "sonner";

type View = "chat" | "dashboard" | "portfolio" | "budget" | "goals" | "documents" | "settings";

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const hasOnboarded = useUserStore((s) => s.hasOnboarded);

  const { conversations, activeConversationId, setActive, addConversation } = useConversationStore();
  const activeConv = conversations.find((c) => c.id === activeConversationId) ?? null;

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

  // Auto-create first conversation when user navigates to chat with none selected
  async function handleViewChange(v: View) {
    setView(v);
    if (v === "chat" && !activeConversationId) {
      try {
        const conv = await createConversation();
        addConversation(conv);
        setActive(conv.id);
      } catch {
        // backend might not be ready; user can retry via "New chat" button
      }
    }
  }

  function handleSelectConversation(conv: Conversation) {
    setActive(conv.id);
    setView("chat");
  }

  if (!hasOnboarded) {
    return <OnboardingWizard />;
  }

  return (
    <div className="flex h-screen bg-[hsl(var(--bg))] text-[hsl(var(--text))]">
      <Sidebar
        view={view}
        onChange={handleViewChange}
        healthy={healthy}
        onSelectConversation={handleSelectConversation}
        activeConvId={activeConversationId}
      />
      <main className="flex-1 overflow-y-auto p-8">
        {view === "dashboard" && <Dashboard />}
        {view === "portfolio" && <Portfolio />}
        {view === "budget" && <Budget />}
        {view === "settings" && <Settings />}
        {view === "chat" && activeConv ? (
          <ChatPanel convId={activeConv.id} threadId={activeConv.thread_id} />
        ) : view === "chat" && !activeConv ? (
          <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
            <div className="card-muted text-sm">
              Start a conversation by clicking <span className="font-semibold text-accent">New chat</span> in the sidebar.
            </div>
          </div>
        ) : null}
        {view !== "dashboard" && view !== "chat" && view !== "settings" && view !== "portfolio" && view !== "budget" && (
          <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
            <div className="card-muted">
              <p className="text-sm">
                <span className="font-semibold capitalize">{view}</span> view —
                placeholder. Implementation coming next.
              </p>
            </div>
          </div>
        )}
      </main>
      <footer className="fixed bottom-2 left-1/2 -translate-x-1/2 text-[10px] text-[hsl(var(--text-muted))]">
        AI-generated suggestions, not financial advice. Consult a licensed advisor.
      </footer>
    </div>
  );
}
