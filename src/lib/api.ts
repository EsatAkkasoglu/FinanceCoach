/**
 * FastAPI sidecar client.
 *
 * Backend URL: localhost:PORT — Tauri sets `TAURI_FINCOACH_PORT` at spawn.
 * Falls back to 8765 for `pnpm dev` outside Tauri.
 */

const PORT = (import.meta.env.TAURI_FINCOACH_PORT as string | undefined) ?? "8765";
export const API_BASE = `http://localhost:${PORT}`;

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
  icon: "trending_up" | "trending_down" | "sparkles" | "alert_circle";
  label: string;
  text: string;
  tone: "positive" | "negative" | "neutral" | "warning";
}

export interface ChatEvent {
  type:
    | "agent_start"
    | "agent_done"
    | "tool_call"
    | "tool_result"
    | "token"
    | "citations"
    | "agent_message"
    | "done"
    | "error";
  payload: Record<string, unknown>;
}

export interface Citation {
  tool: string;
  args: Record<string, unknown>;
  agent?: string;
}

export async function ping() {
  const r = await fetch(`${API_BASE}/health`);
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json() as Promise<{ status: string; version: string; demo_mode: boolean; model: string }>;
}

export async function listPortfolio() {
  const r = await fetch(`${API_BASE}/portfolio`);
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
  const r = await fetch(`${API_BASE}/portfolio/holdings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ ok: true; id: number; ticker: string }>;
}

export async function updateHolding(id: number, patch: Partial<HoldingInput>) {
  const r = await fetch(`${API_BASE}/portfolio/holdings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function deleteHolding(id: number) {
  const r = await fetch(`${API_BASE}/portfolio/holdings/${id}`, { method: "DELETE" });
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
  const r = await fetch(`${API_BASE}/profile`);
  if (!r.ok) throw new Error(`profile ${r.status}`);
  return r.json() as Promise<UserProfile>;
}

export async function updateProfile(patch: Partial<Omit<UserProfile, "id" | "created_at">>) {
  const r = await fetch(`${API_BASE}/profile`, {
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
  const r = await fetch(`${API_BASE}/accounts`);
  if (!r.ok) throw new Error(`accounts ${r.status}`);
  return r.json() as Promise<Account[]>;
}

export async function createAccount(input: AccountInput) {
  const r = await fetch(`${API_BASE}/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Account>;
}

export async function updateAccount(id: number, patch: Partial<AccountInput> & { archived?: boolean }) {
  const r = await fetch(`${API_BASE}/accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Account>;
}

export async function deleteAccount(id: number) {
  const r = await fetch(`${API_BASE}/accounts/${id}`, { method: "DELETE" });
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
  const r = await fetch(`${API_BASE}/transactions${qs ? `?${qs}` : ""}`);
  if (!r.ok) throw new Error(`transactions ${r.status}`);
  return r.json() as Promise<Transaction[]>;
}

export async function createTransaction(input: TransactionInput) {
  const r = await fetch(`${API_BASE}/transactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Transaction>;
}

export async function createTransactionsBulk(items: TransactionInput[]) {
  const r = await fetch(`${API_BASE}/transactions/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ ok: true; created: number }>;
}

export async function updateTransaction(id: number, patch: Partial<TransactionInput>) {
  const r = await fetch(`${API_BASE}/transactions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Transaction>;
}

export async function deleteTransaction(id: number) {
  const r = await fetch(`${API_BASE}/transactions/${id}`, { method: "DELETE" });
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
  const r = await fetch(`${API_BASE}/subscriptions${qs}`);
  if (!r.ok) throw new Error(`subs ${r.status}`);
  return r.json() as Promise<Subscription[]>;
}

export async function createSubscription(input: SubscriptionInput) {
  const r = await fetch(`${API_BASE}/subscriptions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Subscription>;
}

export async function updateSubscription(id: number, patch: Partial<SubscriptionInput> & { active?: boolean }) {
  const r = await fetch(`${API_BASE}/subscriptions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Subscription>;
}

export async function deleteSubscription(id: number) {
  const r = await fetch(`${API_BASE}/subscriptions/${id}`, { method: "DELETE" });
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
}

export async function listGoals() {
  const r = await fetch(`${API_BASE}/goals`);
  if (!r.ok) throw new Error(`goals ${r.status}`);
  return r.json() as Promise<Goal[]>;
}

export async function createGoal(input: Omit<Goal, "id">) {
  const r = await fetch(`${API_BASE}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Goal>;
}

export async function updateGoal(id: number, patch: Partial<Omit<Goal, "id">>) {
  const r = await fetch(`${API_BASE}/goals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Goal>;
}

export async function deleteGoal(id: number) {
  const r = await fetch(`${API_BASE}/goals/${id}`, { method: "DELETE" });
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
  const r = await fetch(`${API_BASE}/budget/summary${qs}`);
  if (!r.ok) throw new Error(`summary ${r.status}`);
  return r.json() as Promise<BudgetSummary>;
}

// ── Document parsing ────────────────────────────────────────────────────────

export async function parseDocument(file: File, signal?: AbortSignal) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API_BASE}/documents/parse`, {
    method: "POST",
    body: fd,
    signal,
  });
  if (!r.ok) throw new Error(await r.text() || `parse ${r.status}`);
  return r.json() as Promise<ProfileExtraction>;
}

export async function getBriefing() {
  const r = await fetch(`${API_BASE}/briefing`);
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
  const r = await fetch(`${API_BASE}/onboarding`, {
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
  const r = await fetch(`${API_BASE}/conversations`);
  if (!r.ok) throw new Error(`list conversations ${r.status}`);
  return r.json();
}

export async function createConversation(title?: string): Promise<Conversation> {
  const r = await fetch(`${API_BASE}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title ?? null }),
  });
  if (!r.ok) throw new Error(`create conversation ${r.status}`);
  return r.json();
}

export async function updateConversationTitle(id: string, title: string): Promise<void> {
  await fetch(`${API_BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${API_BASE}/conversations/${id}`, { method: "DELETE" });
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
  signal?: AbortSignal
): AsyncGenerator<ChatEvent> {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, thread_id: threadId, conv_id: convId }),
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

// ── FX ──────────────────────────────────────────────────────────────────────

export interface FxRates {
  base: string;
  rates: Record<string, number>;
  fetched_at: number;
}

export async function getFxRates(base: string): Promise<FxRates> {
  const r = await fetch(`${API_BASE}/fx/rates?base=${encodeURIComponent(base)}`);
  if (!r.ok) throw new Error(`fx ${r.status}`);
  return r.json();
}
