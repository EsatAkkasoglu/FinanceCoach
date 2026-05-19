/**
 * FastAPI sidecar client.
 *
 * In dev, points to localhost:8765. In production (Firebase Hosting + Cloud Run)
 * set VITE_API_BASE to the Cloud Run service URL or use Firebase rewrites.
 */

import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  signOut,
} from "firebase/auth";
import { auth, googleProvider } from "./firebase";

const PORT = (import.meta.env.TAURI_FINCOACH_PORT as string | undefined) ?? "8765";
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? `http://localhost:${PORT}`;

// ── Auth token (Firebase ID token, fetched dynamically) ───────────────────
async function getBearerToken(): Promise<string | null> {
  try {
    return (await auth.currentUser?.getIdToken()) ?? null;
  } catch {
    return null;
  }
}

/** @deprecated No-op — tokens are managed by Firebase. */
export function getAuthToken(): string | null { return null; }
/** @deprecated No-op — tokens are managed by Firebase. */
export function setAuthToken(_token: string | null) {}

/** Subscribers notified on 401 so the app can redirect to /login. */
type UnauthorizedHandler = () => void;
const unauthorizedHandlers = new Set<UnauthorizedHandler>();
export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandlers.add(handler);
  return () => unauthorizedHandlers.delete(handler);
}

/** Fetch wrapper that attaches a fresh Firebase ID token and handles 401. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getBearerToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (resp.status === 401) {
    unauthorizedHandlers.forEach((h) => h());
  }
  return resp;
}

// ── Auth API ───────────────────────────────────────────────────────────────
export interface AuthUser {
  id: number;
  username: string;
  name: string;
  avatar: string;
  has_onboarded: boolean;
}

/** Sync the current Firebase user with the backend and return the local profile. */
async function syncWithBackend(): Promise<AuthUser> {
  const r = await apiFetch("/auth/firebase", { method: "POST" });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(d.detail || `sync failed ${r.status}`);
  }
  return r.json() as Promise<AuthUser>;
}

export async function login(email: string, password: string): Promise<AuthUser> {
  await signInWithEmailAndPassword(auth, email, password);
  return syncWithBackend();
}

export async function register(email: string, password: string): Promise<AuthUser> {
  await createUserWithEmailAndPassword(auth, email, password);
  return syncWithBackend();
}

export async function loginWithGoogle(): Promise<AuthUser> {
  await signInWithPopup(auth, googleProvider);
  return syncWithBackend();
}

export async function fetchMe(): Promise<AuthUser | null> {
  if (!auth.currentUser) return null;
  const r = await apiFetch("/auth/firebase", { method: "POST" });
  if (!r.ok) return null;
  return r.json() as Promise<AuthUser>;
}

export async function logout(): Promise<void> {
  await signOut(auth);
}

export interface Holding {
  id?: number;
  ticker: string;
  asset_class: "stock" | "crypto" | "cash" | "bond" | "etf";
  quantity: number;
  cost_basis: number;
  acquired_at?: string | null;
  // Present when fetched from /portfolio (server enriches with prices)
  current_price?: number;
  current_value?: number;
  cost_total?: number;
  pnl?: number;
  pnl_pct?: number;
  currency?: string;
}

export interface PortfolioTotals {
  value: number;
  cost: number;
  pnl: number;
  pnl_pct: number;
  count: number;
}

export interface BriefingItem {
  icon:
    | "trending_up"
    | "trending_down"
    | "sparkles"
    | "alert_circle"
    | "flame"
    | "newspaper"
    | "coins";
  label: string;
  text: string;
  tone: "positive" | "negative" | "neutral" | "warning";
  url?: string;
}

export interface ChatEvent {
  type:
    | "agent_start"
    | "agent_done"
    | "tool_call"
    | "tool_result"
    | "token"
    | "citations"
    | "suggestions"
    | "agent_message"
    | "agent_reasoning"
    | "agent_error"
    | "done"
    | "error";
  payload: Record<string, unknown>;
}

export interface ReasoningDriver {
  source: string;
  factor: string;
  impact: string;
}

export interface AllocationDrivers {
  asset_class: string;
  drivers: ReasoningDriver[];
}

export interface ReasoningPayload {
  agent: "advisor" | "risk_profiler" | string;
  why_summary?: string;
  key_drivers: ReasoningDriver[];
  allocation_drivers?: AllocationDrivers[];
  risk_score?: number;
  profile?: string;
  equity_band?: [number | undefined, number | undefined];
}

export interface Citation {
  tool: string;
  args: Record<string, unknown>;
  agent?: string;
}

export async function ping() {
  const r = await apiFetch(`/health`);
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json() as Promise<{ status: string; version: string; demo_mode: boolean; model: string }>;
}

export async function listPortfolio() {
  const r = await apiFetch(`/portfolio`);
  return r.json() as Promise<{ holdings: Holding[]; totals: PortfolioTotals }>;
}

// ── Holding CRUD ────────────────────────────────────────────────────────────

export interface HoldingInput {
  ticker: string;
  quantity: number;
  cost_basis: number;
  asset_class: "stock" | "etf" | "crypto" | "bond" | "cash";
}

export async function addHolding(input: HoldingInput) {
  const r = await apiFetch(`/portfolio/holdings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ ok: true; id: number; ticker: string }>;
}

export async function updateHolding(id: number, patch: Partial<HoldingInput>) {
  const r = await apiFetch(`/portfolio/holdings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function deleteHolding(id: number) {
  const r = await apiFetch(`/portfolio/holdings/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

// ── Profile ─────────────────────────────────────────────────────────────────

export interface UserProfile {
  id: number;
  name: string;
  avatar: string;
  monthly_income: number;
  risk_score: number;
  risk_profile: "conservative" | "balanced" | "aggressive";
  roast_mode: boolean;
  created_at: string | null;
}

export async function getProfile() {
  const r = await apiFetch(`/profile`);
  if (!r.ok) throw new Error(`profile ${r.status}`);
  return r.json() as Promise<UserProfile>;
}

export async function updateProfile(patch: Partial<Omit<UserProfile, "id" | "created_at">>) {
  const r = await apiFetch(`/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<UserProfile>;
}

// ── Document parsing ────────────────────────────────────────────────────────

export interface HoldingSuggestion {
  ticker: string;
  asset_class: "stock" | "etf" | "crypto" | "bond" | "cash";
  quantity: number | null;
  cost_basis: number | null;
  currency: string | null;
  confidence: number;
  source_text: string | null;
}

export interface TransactionSuggestion {
  occurred_on: string | null;
  amount: number | null;
  currency: string | null;
  type: "income" | "expense" | "transfer" | "unknown";
  category: string | null;
  description: string | null;
  confidence: number;
}

export interface ProfileSuggestion {
  name: string | null;
  monthly_income: number | null;
  currency: string | null;
  risk_signals: string[];
  confidence: number;
}

export interface ProfileExtraction {
  doc_type:
    | "bank_statement" | "broker_statement" | "portfolio_screenshot"
    | "invoice" | "receipt" | "id_document" | "salary_slip" | "other";
  doc_type_confidence: number;
  summary: string;
  suggested_holdings: HoldingSuggestion[];
  suggested_transactions: TransactionSuggestion[];
  suggested_profile: ProfileSuggestion | null;
  missing_or_unclear: string[];
  follow_up_questions: string[];
  needs_better_document: string | null;
}

// ── Budget: accounts ────────────────────────────────────────────────────────

export type AccountKind = "cash" | "checking" | "savings" | "credit_card";

export interface Account {
  id: number;
  name: string;
  kind: AccountKind;
  balance: number;
  currency: string;
  institution: string | null;
  color: string;
  archived: boolean;
}

export interface AccountInput {
  name: string;
  kind: AccountKind;
  balance: number;
  currency: string;
  institution?: string | null;
  color?: string;
}

export async function listAccounts() {
  const r = await apiFetch(`/accounts`);
  if (!r.ok) throw new Error(`accounts ${r.status}`);
  return r.json() as Promise<Account[]>;
}

export async function createAccount(input: AccountInput) {
  const r = await apiFetch(`/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Account>;
}

export async function updateAccount(id: number, patch: Partial<AccountInput> & { archived?: boolean }) {
  const r = await apiFetch(`/accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Account>;
}

export async function deleteAccount(id: number) {
  const r = await apiFetch(`/accounts/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

// ── Budget: transactions ────────────────────────────────────────────────────

export type TxType = "income" | "expense" | "transfer";
export type TxSource = "manual" | "upload" | "chat" | "subscription";

export interface Transaction {
  id: number;
  occurred_on: string;
  type: TxType;
  amount: number;
  currency: string;
  category: string;
  description: string;
  source: TxSource;
  account_id: number | null;
  subscription_id: number | null;
}

export interface TransactionInput {
  occurred_on: string;
  type: TxType;
  amount: number;
  currency: string;
  category: string;
  description?: string;
  source?: TxSource;
  account_id?: number | null;
  subscription_id?: number | null;
}

export interface TransactionFilters {
  from?: string;
  to?: string;
  type?: TxType;
  category?: string;
  account_id?: number;
}

export async function listTransactions(filters: TransactionFilters = {}) {
  const params = new URLSearchParams();
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.type) params.set("type", filters.type);
  if (filters.category) params.set("category", filters.category);
  if (filters.account_id != null) params.set("account_id", String(filters.account_id));
  const qs = params.toString();
  const r = await apiFetch(`/transactions${qs ? `?${qs}` : ""}`);
  if (!r.ok) throw new Error(`transactions ${r.status}`);
  return r.json() as Promise<Transaction[]>;
}

export async function createTransaction(input: TransactionInput) {
  const r = await apiFetch(`/transactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Transaction>;
}

export async function createTransactionsBulk(items: TransactionInput[]) {
  const r = await apiFetch(`/transactions/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ ok: true; created: number }>;
}

export async function updateTransaction(id: number, patch: Partial<TransactionInput>) {
  const r = await apiFetch(`/transactions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Transaction>;
}

export async function deleteTransaction(id: number) {
  const r = await apiFetch(`/transactions/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

// ── Budget: subscriptions ───────────────────────────────────────────────────

export type SubCycle = "weekly" | "monthly" | "quarterly" | "yearly";
export type SubDirection = "income" | "expense";

export interface Subscription {
  id: number;
  name: string;
  amount: number;
  currency: string;
  cycle: SubCycle;
  direction: SubDirection;
  next_charge_on: string | null;
  category: string;
  icon: string | null;
  account_id: number | null;
  active: boolean;
}

export interface SubscriptionInput {
  name: string;
  amount: number;
  currency: string;
  cycle: SubCycle;
  direction?: SubDirection;
  next_charge_on?: string | null;
  category?: string;
  icon?: string | null;
  account_id?: number | null;
}

export async function listSubscriptions(active?: boolean) {
  const qs = active === undefined ? "" : `?active=${active}`;
  const r = await apiFetch(`/subscriptions${qs}`);
  if (!r.ok) throw new Error(`subs ${r.status}`);
  return r.json() as Promise<Subscription[]>;
}

export async function createSubscription(input: SubscriptionInput) {
  const r = await apiFetch(`/subscriptions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Subscription>;
}

export async function updateSubscription(id: number, patch: Partial<SubscriptionInput> & { active?: boolean }) {
  const r = await apiFetch(`/subscriptions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Subscription>;
}

export async function deleteSubscription(id: number) {
  const r = await apiFetch(`/subscriptions/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

// ── Budget: goals ───────────────────────────────────────────────────────────

export interface Goal {
  id: number;
  title: string;
  target_amount: number;
  current_amount: number;
  target_date: string | null;
  icon: string;
  currency: string;
}

export async function listGoals() {
  const r = await apiFetch(`/goals`);
  if (!r.ok) throw new Error(`goals ${r.status}`);
  return r.json() as Promise<Goal[]>;
}

export async function createGoal(input: Omit<Goal, "id">) {
  const r = await apiFetch(`/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Goal>;
}

export async function updateGoal(id: number, patch: Partial<Omit<Goal, "id">>) {
  const r = await apiFetch(`/goals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Goal>;
}

export async function deleteGoal(id: number) {
  const r = await apiFetch(`/goals/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

// ── Budget: summary ─────────────────────────────────────────────────────────

export interface BudgetSummary {
  month: string;
  cash_on_hand: Record<string, number>;
  credit_card_debt: Record<string, number>;
  income_mtd: Record<string, number>;
  expense_mtd: Record<string, number>;
  income_prev_month: Record<string, number>;
  expense_prev_month: Record<string, number>;
  top_categories: { category: string; currency: string; amount: number }[];
  recurring: {
    income_monthly_by_currency: Record<string, number>;
    expense_monthly_by_currency: Record<string, number>;
    upcoming: Subscription[];
  };
}

export async function getBudgetSummary(month?: string) {
  const qs = month ? `?month=${month}` : "";
  const r = await apiFetch(`/budget/summary${qs}`);
  if (!r.ok) throw new Error(`summary ${r.status}`);
  return r.json() as Promise<BudgetSummary>;
}

// ── Document parsing ────────────────────────────────────────────────────────

export async function parseDocument(file: File, signal?: AbortSignal) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`/documents/parse`, {
    method: "POST",
    body: fd,
    signal,
  });
  if (!r.ok) throw new Error(await r.text() || `parse ${r.status}`);
  return r.json() as Promise<ProfileExtraction>;
}

export async function getBriefing() {
  const r = await apiFetch(`/briefing`);
  return r.json() as Promise<{ items: BriefingItem[]; as_of: string }>;
}

export interface OnboardingPayload {
  name: string;
  avatar: string;
  monthly_income: number;
  risk_score: number;
  risk_profile: "conservative" | "balanced" | "aggressive";
  spending_pace: number;
  goal: {
    title: string;
    target_amount: number;
    target_date: string;
    icon: string;
  };
  holdings: Array<{
    ticker: string;
    quantity: number;
    cost_basis: number;
    asset_class: "stock" | "crypto" | "cash" | "etf";
  }>;
}

export async function submitOnboarding(payload: OnboardingPayload) {
  const r = await apiFetch(`/onboarding`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`onboarding failed (${r.status}): ${text || r.statusText}`);
  }
  return r.json() as Promise<{ ok: true; user_id: number }>;
}

// ── Conversation types ──────────────────────────────────────────────────────

export interface Conversation {
  id: string;
  thread_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export async function listConversations(): Promise<Conversation[]> {
  const r = await apiFetch(`/conversations`);
  if (!r.ok) throw new Error(`list conversations ${r.status}`);
  return r.json();
}

export async function createConversation(title?: string): Promise<Conversation> {
  const r = await apiFetch(`/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title ?? null }),
  });
  if (!r.ok) throw new Error(`create conversation ${r.status}`);
  return r.json();
}

export async function autotitleConversation(id: string, message: string): Promise<string | null> {
  try {
    const r = await apiFetch(`/conversations/${id}/autotitle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!r.ok) return null;
    const data = (await r.json()) as { ok: boolean; title: string };
    return data.title ?? null;
  } catch {
    return null;
  }
}

export async function updateConversationTitle(id: string, title: string): Promise<void> {
  await apiFetch(`/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  await apiFetch(`/conversations/${id}`, { method: "DELETE" });
}

// ── Chat streaming ──────────────────────────────────────────────────────────

/**
 * Stream a chat response from the supervisor. Each yielded event corresponds
 * to one Server-Sent Event from the backend.
 * History is now managed server-side via LangGraph checkpointer — only
 * thread_id and the new message are required.
 */
export async function* streamChat(
  message: string,
  threadId: string,
  convId: string,
  signal?: AbortSignal,
  displayCurrency?: string,
): AsyncGenerator<ChatEvent> {
  const resp = await apiFetch(`/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      message,
      thread_id: threadId,
      conv_id: convId,
      display_currency: displayCurrency,
    }),
    signal,
  });
  if (!resp.body) throw new Error("no stream body");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // sse-starlette emits "\r\n" line breaks and "\r\n\r\n" event separators;
  // browsers that proxy through HTTP/1.1 may also emit "\n\n". Match either.
  const SEPARATOR = /\r?\n\r?\n/;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let match: RegExpExecArray | null;
    while ((match = SEPARATOR.exec(buffer)) !== null) {
      const chunk = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      const event = parseSSE(chunk);
      if (event) yield event;
    }
  }
}

function parseSSE(chunk: string): ChatEvent | null {
  const lines = chunk.split(/\r?\n/);
  let type = "";
  let data = "";
  for (const line of lines) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!type) return null;
  try {
    return { type: type as ChatEvent["type"], payload: data ? JSON.parse(data) : {} };
  } catch {
    return { type: "error", payload: { raw: data } };
  }
}

// ── Message feedback ───────────────────────────────────────────────────────

export interface FeedbackPayload {
  thread_id: string;
  message_id: string;
  rating: "up" | "down";
  reason?: string;
  agent?: string;
  excerpt?: string;
}

export async function sendFeedback(payload: FeedbackPayload): Promise<void> {
  const r = await apiFetch(`/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`feedback ${r.status}`);
}

// ── FX ──────────────────────────────────────────────────────────────────────

export interface FxRates {
  base: string;
  rates: Record<string, number>;
  fetched_at: number;
}

export async function getFxRates(base: string): Promise<FxRates> {
  const r = await apiFetch(`/fx/rates?base=${encodeURIComponent(base)}`);
  if (!r.ok) throw new Error(`fx ${r.status}`);
  return r.json();
}

// ── Symbol autocomplete ─────────────────────────────────────────────────────

export interface SymbolSuggestion {
  ticker: string;
  description: string;
  asset_class: string;
  source: string;
  region?: string | null;
}

export async function resolveSymbol(q: string, limit = 10): Promise<SymbolSuggestion[]> {
  const r = await apiFetch(`/symbols/resolve?q=${encodeURIComponent(q)}&limit=${limit}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { results: SymbolSuggestion[] };
  return data.results;
}

// ── Turkish funds (TEFAS) ───────────────────────────────────────────────────

export interface FundRow {
  code: string;
  title: string | null;
  price: number | null;
  change_pct?: number | null;
  category?: string | null;
  risk?: string | null;
  return_1m?: number | null;
  return_3m?: number | null;
  return_6m?: number | null;
  return_1y?: number | null;
  return_ytd?: number | null;
  category_rank?: number | null;
  category_total?: number | null;
  as_of: string | null;
}

export interface FundHistoryPoint {
  date: string;
  price: number;
}

export async function searchFunds(
  q: string,
  kind: "mutual" | "pension" = "mutual",
  limit = 20,
): Promise<FundRow[]> {
  const r = await apiFetch(
    `/funds/search?q=${encodeURIComponent(q)}&kind=${kind}&limit=${limit}`,
  );
  if (!r.ok) return [];
  const data = (await r.json()) as { results: FundRow[] };
  return data.results;
}

export async function topFunds(
  metric: "best_rank" | "worst_rank" = "best_rank",
  limit = 20,
  category?: string,
): Promise<FundRow[]> {
  const params = new URLSearchParams({ metric, limit: String(limit) });
  if (category) params.set("category", category);
  const r = await apiFetch(`/funds/top?${params.toString()}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { results: FundRow[] };
  return data.results;
}

export async function fundQuote(code: string): Promise<FundRow | null> {
  const r = await apiFetch(`/funds/${encodeURIComponent(code)}/quote`);
  if (!r.ok) return null;
  return r.json();
}

export async function fundHistory(code: string, days = 90): Promise<FundHistoryPoint[]> {
  const r = await apiFetch(`/funds/${encodeURIComponent(code)}/history?days=${days}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { points: FundHistoryPoint[] };
  return data.points;
}

// ── Insights (scanners + per-ticker analysis) ───────────────────────────────

export interface EightDimResult {
  ticker: string;
  final_score: number | null;
  recommendation: string | null;
  dimensions: Record<string, { score: number; [k: string]: unknown }>;
  weights: Record<string, number>;
  unavailable_dimensions: string[];
  degraded?: boolean;
  error?: string;
}

export async function analyzeEightDim(ticker: string, fast = false): Promise<EightDimResult> {
  const r = await apiFetch(`/insights/8dim/${encodeURIComponent(ticker)}?fast=${fast ? 1 : 0}`);
  return r.json();
}

export interface TechnicalsResult {
  ticker: string;
  sma?: { period: number; value: number | null; signal: string };
  rsi?: { period: number; value: number | null; signal: string };
  current_price?: number | null;
  error?: string;
}

export async function getTechnicals(ticker: string): Promise<TechnicalsResult> {
  const r = await apiFetch(`/insights/technicals/${encodeURIComponent(ticker)}`);
  return r.json();
}

export interface DividendResult {
  ticker: string;
  yield?: number | null;
  payout_ratio?: number | null;
  growth_5y_cagr?: number | null;
  consecutive_increases?: number | null;
  safety_score?: number | null;
  income_rating?: string | null;
  error?: string;
}

export async function getDividend(ticker: string): Promise<DividendResult> {
  const r = await apiFetch(`/insights/dividend/${encodeURIComponent(ticker)}`);
  return r.json();
}

export interface NewsArticle {
  title: string;
  source: string;
  published_at?: string;
  url: string;
  snippet?: string;
}

export async function searchNews(query: string, limit = 5): Promise<NewsArticle[]> {
  const r = await apiFetch(
    `/insights/news?q=${encodeURIComponent(query)}&limit=${limit}`,
  );
  if (!r.ok) return [];
  const data = (await r.json()) as { articles: NewsArticle[] };
  return data.articles;
}

export interface TrendsResult {
  top_gainers?: { ticker: string; price: number | null; change_pct: number | null; volume: number | null }[];
  top_losers?: { ticker: string; price: number | null; change_pct: number | null; volume: number | null }[];
  most_active?: { ticker: string; price: number | null; change_pct: number | null; volume: number | null }[];
  crypto_trending?: { name: string; symbol: string; rank?: number | null }[];
  crypto_global?: { market_cap_usd?: number; btc_dominance?: number; market_cap_change_pct_24h?: number };
  as_of?: string;
}

export async function getTrends(): Promise<TrendsResult> {
  const r = await apiFetch(`/insights/trends`);
  return r.json();
}

export interface RumorItem {
  title: string;
  ticker?: string | null;
  source: string;
  sentiment?: number;
  sentiment_label?: string;
  relevance?: number;
  impact_score?: number;
  category?: string;
  url: string;
  published_at?: string;
}

export async function getRumors(): Promise<RumorItem[]> {
  const r = await apiFetch(`/insights/rumors`);
  if (!r.ok) return [];
  const data = (await r.json()) as { rumors: RumorItem[] };
  return data.rumors;
}

// ── Memory / conversation search ────────────────────────────────────────────

export interface MemoryHit {
  text: string;
  metadata: Record<string, unknown>;
}

export async function searchMemory(q: string, k = 5): Promise<MemoryHit[]> {
  const r = await apiFetch(`/memory/search?q=${encodeURIComponent(q)}&k=${k}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { hits: MemoryHit[] };
  return data.hits;
}

// ── Net worth history ──────────────────────────────────────────────────────

export interface NetWorthPoint {
  date: string;
  value: number;
  currency: string;
}

export async function captureNetWorth(value: number, currency: string): Promise<NetWorthPoint> {
  const r = await apiFetch(`/networth/snapshot`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value, currency }),
  });
  if (!r.ok) throw new Error(`networth snapshot ${r.status}`);
  return r.json();
}

export async function netWorthHistory(days = 30): Promise<NetWorthPoint[]> {
  const r = await apiFetch(`/networth/history?days=${days}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { points: NetWorthPoint[] };
  return data.points;
}
