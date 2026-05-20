/**
 * Zustand stores — split by domain to keep updates focused.
 *
 * - useUserStore       profile, risk score, goals
 * - usePortfolioStore  holdings + last refresh time
 * - useChatStore       chat history + streaming state
 * - useAgentVizStore   live agent activity events for the agent graph viz
 * - useSettingsStore   theme, demo mode, roast mode
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AuthUser, Conversation } from "@/lib/api";

// ----- Auth -----
interface AuthState {
  user: AuthUser | null;
  ready: boolean; // becomes true after the initial /auth/me check completes
  setUser: (user: AuthUser | null) => void;
  setReady: (ready: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  ready: false,
  setUser: (user) => set({ user }),
  setReady: (ready) => set({ ready }),
}));

// ----- Settings -----
type Theme = "dark" | "light";

export type GeminiModelId =
  | "gemini-3.1-flash-lite-preview"
  | "gemini-2.5-pro"
  | "gemini-2.5-flash"
  | "gemini-2.5-flash-lite"
  | "gemini-2.0-flash"
  | "gemini-2.0-flash-lite";

export type DisplayCurrency = "TRY" | "USD" | "EUR";

interface SettingsState {
  theme: Theme;
  demoMode: boolean;
  roastMode: boolean;
  geminiApiKey: string;
  newsApiKey: string;
  model: GeminiModelId;
  temperature: number;
  displayCurrency: DisplayCurrency;
  toggleTheme: () => void;
  setDemoMode: (v: boolean) => void;
  setRoastMode: (v: boolean) => void;
  setGeminiApiKey: (v: string) => void;
  setNewsApiKey: (v: string) => void;
  setModel: (v: GeminiModelId) => void;
  setTemperature: (v: number) => void;
  setDisplayCurrency: (v: DisplayCurrency) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: "dark",
      demoMode: false,
      roastMode: false,
      geminiApiKey: "",
      newsApiKey: "",
      model: "gemini-3.1-flash-lite-preview",
      temperature: 0.3,
      displayCurrency: "TRY",
      toggleTheme: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setDemoMode: (v) => set({ demoMode: v }),
      setRoastMode: (v) => set({ roastMode: v }),
      setGeminiApiKey: (v) => set({ geminiApiKey: v }),
      setNewsApiKey: (v) => set({ newsApiKey: v }),
      setModel: (v) => set({ model: v }),
      setTemperature: (v) => set({ temperature: v }),
      setDisplayCurrency: (v) => set({ displayCurrency: v }),
    }),
    { name: "fincoach-settings" }
  )
);

// ----- User -----
type RiskProfile = "conservative" | "balanced" | "aggressive";

interface UserState {
  hasOnboarded: boolean;
  name: string;
  avatar: string;
  monthlyIncome: number;
  riskScore: number;
  riskProfile: RiskProfile;
  setProfile: (p: Partial<UserState>) => void;
  completeOnboarding: () => void;
  resetOnboarding: () => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      hasOnboarded: false,
      name: "",
      avatar: "fox",
      monthlyIncome: 0,
      riskScore: 50,
      riskProfile: "balanced",
      setProfile: (p) => set(p),
      completeOnboarding: () => set({ hasOnboarded: true }),
      resetOnboarding: () =>
        set({ hasOnboarded: false, name: "", monthlyIncome: 0, riskScore: 50 }),
    }),
    { name: "fincoach-user" }
  )
);

// ----- Chat -----
export interface Citation {
  tool: string;
  args: Record<string, unknown>;
  agent?: string;
  result?: string;
}

export interface ToolActivity {
  runId: string;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done";
  result?: string;
}

export interface ReasoningDriverLocal {
  source: string;
  factor: string;
  impact: string;
}

export interface ReasoningEntry {
  agent: string;
  why_summary?: string;
  key_drivers: ReasoningDriverLocal[];
  allocation_drivers?: { asset_class: string; drivers: ReasoningDriverLocal[] }[];
  risk_score?: number;
  profile?: string;
  equity_band?: [number | undefined, number | undefined];
}

export type MessageAttachmentKind = "image" | "pdf" | "text" | "spreadsheet" | "code" | "binary";

export interface MessageAttachment {
  id: string;
  name: string;
  mime: string;
  kind: MessageAttachmentKind;
  size: number;
  summary?: string;
  excerpt?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: MessageAttachment[];
  agent?: string;
  citations?: Citation[];
  steps?: ToolActivity[];
  suggestions?: string[];
  reasoning?: ReasoningEntry[];
  createdAt: number;
}

interface ChatState {
  // messages keyed by conversationId — each conversation has its own list
  messagesByConv: Record<string, ChatMessage[]>;
  streaming: boolean;
  appendMessage: (convId: string, m: ChatMessage) => void;
  appendToken: (convId: string, id: string, token: string) => void;
  setMessageAgent: (convId: string, id: string, agent: string) => void;
  addCitations: (convId: string, id: string, citations: Citation[]) => void;
  setMessageSteps: (convId: string, id: string, steps: ToolActivity[]) => void;
  setMessageSuggestions: (convId: string, id: string, suggestions: string[]) => void;
  addReasoning: (convId: string, id: string, entry: ReasoningEntry) => void;
  setStreaming: (v: boolean) => void;
  resetConv: (convId: string) => void;
}

const HISTORY_CAP = 100;

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messagesByConv: {},
      streaming: false,
      appendMessage: (convId, m) =>
        set((s) => {
          const prev = s.messagesByConv[convId] ?? [];
          return { messagesByConv: { ...s.messagesByConv, [convId]: [...prev, m].slice(-HISTORY_CAP) } };
        }),
      appendToken: (convId, id, token) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id ? { ...m, content: m.content + token } : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      setMessageAgent: (convId, id, agent) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id ? { ...m, agent } : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      addCitations: (convId, id, citations) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id ? { ...m, citations: [...(m.citations ?? []), ...citations] } : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      setMessageSteps: (convId, id, steps) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id ? { ...m, steps } : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      setMessageSuggestions: (convId, id, suggestions) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id ? { ...m, suggestions } : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      addReasoning: (convId, id, entry) =>
        set((s) => {
          const msgs = (s.messagesByConv[convId] ?? []).map((m) =>
            m.id === id
              ? {
                  ...m,
                  reasoning: [
                    ...(m.reasoning ?? []).filter((r) => r.agent !== entry.agent),
                    entry,
                  ],
                }
              : m
          );
          return { messagesByConv: { ...s.messagesByConv, [convId]: msgs } };
        }),
      setStreaming: (v) => set({ streaming: v }),
      resetConv: (convId) =>
        set((s) => {
          const next = { ...s.messagesByConv };
          delete next[convId];
          return { messagesByConv: next };
        }),
    }),
    {
      name: "fincoach-chat",
      partialize: (s) => ({ messagesByConv: s.messagesByConv }),
    }
  )
);

// ----- Agent Visualization -----
export interface AgentEvent {
  agent: string;
  status: "idle" | "running" | "done" | "error";
  startedAt: number;
  endedAt?: number;
  toolCount?: number;
}

interface AgentVizState {
  events: Record<string, AgentEvent>;
  setEvent: (e: AgentEvent) => void;
  markDone: (agent: string) => void;
  incrementToolCount: (agent: string) => void;
  clear: () => void;
}

// ----- Dashboard cache -----

export interface DashboardCache {
  holdings: import("@/lib/api").Holding[];
  totals: import("@/lib/api").PortfolioTotals;
  briefing: import("@/lib/api").BriefingItem[];
  fetchedAt: number; // Date.now()
}

interface DashboardState {
  cache: DashboardCache | null;
  loading: boolean;
  setCache: (c: DashboardCache) => void;
  setLoading: (v: boolean) => void;
  invalidate: () => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  cache: null,
  loading: false,
  setCache: (c) => set({ cache: c, loading: false }),
  setLoading: (v) => set({ loading: v }),
  invalidate: () => set({ cache: null }),
}));

// ----- Conversations -----

interface ConversationStore {
  conversations: Conversation[];
  activeConversationId: string | null;
  setConversations: (convs: Conversation[]) => void;
  addConversation: (conv: Conversation) => void;
  removeConversation: (id: string) => void;
  updateTitle: (id: string, title: string) => void;
  setActive: (id: string | null) => void;
}

export const useConversationStore = create<ConversationStore>((set) => ({
  conversations: [],
  activeConversationId: null,
  setConversations: (convs) => set({ conversations: convs }),
  addConversation: (conv) =>
    set((s) => ({ conversations: [conv, ...s.conversations] })),
  removeConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeConversationId: s.activeConversationId === id ? null : s.activeConversationId,
    })),
  updateTitle: (id, title) =>
    set((s) => ({
      conversations: s.conversations.map((c) => (c.id === id ? { ...c, title } : c)),
    })),
  setActive: (id) => set({ activeConversationId: id }),
}));

// ----- Tour -----
interface TourState {
  seen: boolean;
  active: boolean;
  step: number;
  start: () => void;
  next: () => void;
  prev: () => void;
  skip: () => void;
}

export const TOUR_STEPS = [
  {
    title: "FinCoach'a Hoş Geldiniz! 👋",
    body: "Yapay zeka destekli kişisel finansal koçunuz. 7 uzman ajan gelirinizi, harcamalarınızı ve yatırımlarınızı analiz eder.",
    path: "/dashboard",
    navKey: "dashboard",
  },
  {
    title: "Koç — Finansal Yapay Zekanız",
    body: "Her şeyi sorabilirsiniz: \"Bu ay nereye para harcadım?\", \"50.000 TL hedefime ne zaman ulaşırım?\", \"Portföyümü nasıl çeşitlendireyim?\"",
    path: "/chat",
    navKey: "chat",
  },
  {
    title: "Dashboard",
    body: "Tüm hesaplarınızın bakiyesi, bu ayki gelir/gider dengesi ve günlük AI brifingini tek ekranda görün.",
    path: "/dashboard",
    navKey: "dashboard",
  },
  {
    title: "Bütçe",
    body: "İşlemlerinizi kategorilere göre takip edin, aboneliklerinizi yönetin ve aylık harcama trendlerinizi görün.",
    path: "/budget",
    navKey: "budget",
  },
  {
    title: "Hedefler",
    body: "Acil durum fonu, tatil veya ev gibi tasarruf hedefleri oluşturun. Koç, hedeflerinize göre aylık birikim planı yapar.",
    path: "/goals",
    navKey: "goals",
  },
  {
    title: "Portföy",
    body: "Hisse senetleri ve diğer yatırımlarınızı takip edin. Güncel fiyatlar ve kâr/zarar analizi otomatik hesaplanır.",
    path: "/portfolio",
    navKey: "portfolio",
  },
  {
    title: "Keşfet",
    body: "Piyasa haberleri, korku/açgözlülük endeksi ve hisse analizi. Yatırım kararlarınızı destekleyen gerçek zamanlı veriler.",
    path: "/discover",
    navKey: "discover",
  },
] as const;

export const useTourStore = create<TourState>()(
  persist(
    (set) => ({
      seen: false,
      active: false,
      step: 0,
      start: () => set({ active: true, step: 0 }),
      next: () =>
        set((s) => {
          const nextStep = s.step + 1;
          if (nextStep >= TOUR_STEPS.length) return { active: false, seen: true, step: 0 };
          return { step: nextStep };
        }),
      prev: () => set((s) => ({ step: Math.max(0, s.step - 1) })),
      skip: () => set({ active: false, seen: true, step: 0 }),
    }),
    { name: "fincoach-tour" }
  )
);

export const useAgentVizStore = create<AgentVizState>((set) => ({
  events: {},
  setEvent: (e) => set((s) => ({ events: { ...s.events, [e.agent]: { ...s.events[e.agent], ...e } } })),
  markDone: (agent) =>
    set((s) => {
      const prev = s.events[agent];
      if (!prev) return s;
      return {
        events: { ...s.events, [agent]: { ...prev, status: "done", endedAt: Date.now() } },
      };
    }),
  incrementToolCount: (agent) =>
    set((s) => {
      const prev = s.events[agent];
      if (!prev) return s;
      return {
        events: {
          ...s.events,
          [agent]: { ...prev, toolCount: (prev.toolCount ?? 0) + 1 },
        },
      };
    }),
  clear: () => set({ events: {} }),
}));
