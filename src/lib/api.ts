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
  signInWithRedirect,
  getRedirectResult,
  signOut,
} from "firebase/auth";
import { auth, googleProvider } from "./firebase";

const PORT = (import.meta.env.TAURI_FINCOACH_PORT as string | undefined) ?? "8765";
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? `http://localhost:${PORT}`;

// ── Auth token ────────────────────────────────────────────────────────────
export const DEMO_TOKEN_KEY = "fincoach-demo-token";

async function getBearerToken(forceRefresh = false): Promise<string | null> {
  if (auth.currentUser) {
    try {
      // Race the Firebase token refresh against a 8 s deadline.
      // If getIdToken() stalls (Firebase servers slow), we fall through so
      // fetch() still runs and the backend can return 401 rather than hanging.
      const tokenPromise = auth.currentUser.getIdToken(forceRefresh);
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("token_timeout")), 8_000),
      );
      const firebaseToken = await Promise.race([tokenPromise, timeoutPromise]);
      if (firebaseToken) return firebaseToken;
    } catch { /* fall through to demo token */ }
  }
  return localStorage.getItem(DEMO_TOKEN_KEY);
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

/**
 * Fetch wrapper that attaches a fresh Firebase ID token and handles 401.
 * On first 401, force-refreshes the token and retries once before logging out.
 */
const FETCH_TIMEOUT_MS = 25_000;

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  _retried = false,
): Promise<Response> {
  const token = await getBearerToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // Merge caller's signal with a 25 s deadline so we never hang forever.
  const timeout = AbortSignal.timeout(FETCH_TIMEOUT_MS);
  const signal = init.signal
    ? AbortSignal.any([init.signal, timeout])
    : timeout;

  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers, signal });

  if (resp.status === 401 && !_retried && auth.currentUser) {
    // Force-refresh the Firebase ID token and retry once
    const fresh = await getBearerToken(true);
    if (fresh) {
      return apiFetch(path, init, true);
    }
  }
  if (resp.status === 401 && _retried) {
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
  consented?: boolean;
  consent_version?: string | null;
  consent_current?: boolean;
}

// ── Billing ──────────────────────────────────────────────────────────────────

export interface BillingPlan {
  code: string;
  price: number;
  currency: string;
  period: string;
}

export interface BillingPlansResponse {
  provider: string;
  tier: string;
  plans: BillingPlan[];
}

export async function getBillingPlans(): Promise<BillingPlansResponse | null> {
  try {
    const r = await apiFetch("/billing/plans");
    if (!r.ok) return null;
    return (await r.json()) as BillingPlansResponse;
  } catch {
    return null;
  }
}

export type CheckoutResult =
  | { status: "ok"; redirectUrl: string }
  | { status: "unavailable" }   // payments not wired in this deploy yet
  | { status: "error" };        // network / unexpected

/** Start a checkout. Discriminated result so the UI can route each case. */
export async function startCheckout(plan: string, returnUrl: string): Promise<CheckoutResult> {
  try {
    const r = await apiFetch("/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, return_url: returnUrl }),
    });
    if (!r.ok) return { status: "error" };
    const data = (await r.json()) as { redirect_url?: string; status?: string };
    if (data.status === "unavailable") return { status: "unavailable" };
    if (data.redirect_url) return { status: "ok", redirectUrl: data.redirect_url };
    return { status: "error" };
  } catch {
    return { status: "error" };
  }
}

/** Confirm a checkout on the return page. Returns the resulting status. */
export async function finalizeCheckout(
  ref: string,
  params: Record<string, string> = {},
): Promise<{ status: string; tier?: string } | null> {
  try {
    const r = await apiFetch("/billing/finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref, params }),
    });
    if (!r.ok) return { status: "error" };
    return (await r.json()) as { status: string; tier?: string };
  } catch {
    return null;
  }
}

/** sessionStorage flag: a register-mode Google redirect needs consent recorded. */
export const PENDING_CONSENT_KEY = "fincoach-pending-consent";

/** Record KVKK/Terms consent for the signed-in user (current policy version). */
export async function recordConsent(): Promise<boolean> {
  try {
    const r = await apiFetch("/account/consent", { method: "POST" });
    return r.ok;
  } catch {
    return false;
  }
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
  // Use redirect on deployed web (avoids COOP/popup issues), popup in local dev
  if (import.meta.env.PROD) {
    await signInWithRedirect(auth, googleProvider);
    // Execution continues after the page reloads and redirect result is handled
    // in App.tsx via getRedirectResult — this line is never actually reached in prod
    return syncWithBackend();
  }
  await signInWithPopup(auth, googleProvider);
  return syncWithBackend();
}

/** Call once on app startup to complete a pending Google redirect sign-in. */
export async function handleGoogleRedirectResult(): Promise<AuthUser | null> {
  const result = await getRedirectResult(auth);
  if (!result) return null;
  return syncWithBackend();
}

export async function fetchMe(): Promise<AuthUser | null> {
  if (!auth.currentUser) return null;
  const r = await apiFetch("/auth/firebase", { method: "POST" });
  if (!r.ok) return null;
  return r.json() as Promise<AuthUser>;
}

export async function logout(): Promise<void> {
  localStorage.removeItem(DEMO_TOKEN_KEY);
  await signOut(auth);
}

export async function loginDemo(): Promise<AuthUser> {
  const r = await fetch(`${API_BASE}/auth/demo`, {
    method: "POST",
    // Allow 60 s — Cloud Run may be cold-starting (30-90 s first request).
    signal: AbortSignal.timeout(60_000),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error((d as { detail?: string }).detail || "Demo login failed");
  }
  const data = (await r.json()) as { token: string; user: AuthUser };
  localStorage.setItem(DEMO_TOKEN_KEY, data.token);
  return data.user;
}

export interface Holding {
  id?: number;
  ticker: string;
  asset_class: "stock" | "crypto" | "cash" | "bond" | "etf" | "fund";
  quantity: number;
  cost_basis: number;
  acquired_at?: string | null;
  // Present when fetched from /portfolio (server enriches with prices)
  current_price?: number;
  current_value?: number;
  cost_total?: number;
  pnl?: number;
  pnl_pct?: number;
  /** 1-day % change for this position (null when the quote lacks it). */
  change_today?: number | null;
  /** Today's P&L in the holding's native currency (value * change_today/100). */
  day_pnl?: number | null;
  currency?: string;
}

export interface PortfolioTotals {
  value: number;
  cost: number;
  pnl: number;
  pnl_pct: number;
  /** Aggregate day P&L across positions, in mixed native currencies (pre-FX). */
  day_pnl?: number;
  day_pnl_pct?: number;
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
  if (!r.ok) throw new Error(`portfolio ${r.status}`);
  return r.json() as Promise<{ holdings: Holding[]; totals: PortfolioTotals }>;
}

// ── Holding CRUD ────────────────────────────────────────────────────────────

export interface HoldingInput {
  ticker: string;
  quantity: number;
  cost_basis: number;
  asset_class: "stock" | "etf" | "crypto" | "bond" | "cash" | "fund";
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
  extracted_text: string | null;
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

// ── Budget: trend (6-month flow + per-category MoM) ──────────────────────────

export interface BudgetTrendMonth {
  month: string;
  income: number;
  expense: number;
  net: number;
}

export interface CategoryMoM {
  category: string;
  current: number;
  previous: number;
  change_pct: number | null;
}

export interface BudgetTrend {
  months: BudgetTrendMonth[];
  category_mom: CategoryMoM[];
}

export async function getBudgetTrend(months = 6): Promise<BudgetTrend> {
  const r = await apiFetch(`/budget/trend?months=${months}`);
  if (!r.ok) return { months: [], category_mom: [] };
  return r.json() as Promise<BudgetTrend>;
}

// ── News feed (pre-collected, enriched headlines) ────────────────────────────

export interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
  snippet: string | null;
  summary: string | null;
  lang: string;
  category: string | null;
  sentiment: "positive" | "neutral" | "negative" | null;
  sentiment_score: number | null;
  fetched_at: string | null;
}

export interface NewsFeedParams {
  q?: string;
  category?: string;
  lang?: string;
  since?: string;       // ISO datetime
  limit?: number;
}

export async function getNewsFeed(params: NewsFeedParams = {}): Promise<NewsItem[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.category) qs.set("category", params.category);
  if (params.lang) qs.set("lang", params.lang);
  if (params.since) qs.set("since", params.since);
  if (params.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();
  const r = await apiFetch(`/news/feed${query ? `?${query}` : ""}`);
  if (!r.ok) return [];
  const data = (await r.json()) as { items: NewsItem[]; count: number };
  return data.items ?? [];
}

// ── Proactive news alerts + watchlist ────────────────────────────────────────

/** A headline matched to the user's watchlist or the importance threshold. */
export interface NewsAlert {
  id: number;
  reason: string;             // "watchlist:AAPL" | "category:regulation" | "sentiment"
  priority: number;           // 2 = watchlist hit, 1 = importance
  created_at: string | null;
  read: boolean;
  article: {
    id: number;
    title: string;
    url: string;
    source: string;
    summary: string | null;
    snippet: string | null;
    lang: string;
    category: string | null;
    sentiment: "positive" | "neutral" | "negative" | null;
    sentiment_score: number | null;
    tickers: string | null;
    published_at: string | null;
  } | null;
}

export interface NewsAlertsResponse {
  items: NewsAlert[];
  count: number;
  unread_count: number;
}

export async function getNewsAlerts(
  params: { unreadOnly?: boolean; limit?: number } = {},
): Promise<NewsAlertsResponse> {
  const qs = new URLSearchParams();
  if (params.unreadOnly) qs.set("unread_only", "true");
  if (params.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();
  const r = await apiFetch(`/news/alerts${query ? `?${query}` : ""}`);
  if (!r.ok) return { items: [], count: 0, unread_count: 0 };
  return r.json() as Promise<NewsAlertsResponse>;
}

/** Mark the given alert ids read, or all of the user's alerts when ids omitted. */
export async function markAlertsRead(ids?: number[]): Promise<number> {
  const r = await apiFetch(`/news/alerts/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ids ? { ids } : {}),
  });
  if (!r.ok) return 0;
  const data = (await r.json()) as { ok: boolean; updated: number };
  return data.updated ?? 0;
}

export type WatchKind = "symbol" | "keyword";

export interface WatchlistItem {
  id: number;
  kind: WatchKind;
  value: string;
}

export async function listWatchlist(): Promise<WatchlistItem[]> {
  const r = await apiFetch(`/news/watchlist`);
  if (!r.ok) return [];
  const data = (await r.json()) as { items: WatchlistItem[] };
  return data.items ?? [];
}

export async function addWatchlistItem(kind: WatchKind, value: string): Promise<WatchlistItem | null> {
  const r = await apiFetch(`/news/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, value }),
  });
  if (!r.ok) return null;
  return r.json() as Promise<WatchlistItem>;
}

export async function removeWatchlistItem(id: number): Promise<boolean> {
  const r = await apiFetch(`/news/watchlist/${id}`, { method: "DELETE" });
  return r.ok;
}

// ── Waitlist (landing early-access — Phase 0 demand validation) ───────────────

/** Record an early-access signup. Public endpoint; resolves true on success. */
export async function joinWaitlist(
  email: string,
  tier?: string,
  source?: string,
): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/waitlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, tier, source }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

// ── Usage / plan limits ──────────────────────────────────────────────────────

export interface UsageInfo {
  period: string;
  tier: string;
  used: number;
  limit: number | null;
  remaining: number | null;
  unlimited: boolean;
}

/** Current month's metered usage for the signed-in user. Null on failure. */
export async function getUsage(): Promise<UsageInfo | null> {
  try {
    const r = await apiFetch("/usage");
    if (!r.ok) return null;
    return (await r.json()) as UsageInfo;
  } catch {
    return null;
  }
}

/** KVKK right to erasure: delete the signed-in user + all their data. */
export async function deleteMyAccount(): Promise<boolean> {
  const r = await apiFetch("/account", { method: "DELETE" });
  return r.ok;
}

/** Total waitlist signups, for landing social proof. Resolves null on failure. */
export async function getWaitlistCount(): Promise<number | null> {
  try {
    const r = await fetch(`${API_BASE}/waitlist/count`);
    if (!r.ok) return null;
    const data = (await r.json()) as { count?: number };
    return typeof data.count === "number" ? data.count : null;
  } catch {
    return null;
  }
}

// ── Documents ────────────────────────────────────────────────────────────────

export interface DocumentEntry {
  filename: string;
  created_at: number;      // unix ts
  created_at_iso: string;  // ISO-8601
  chunk_count: number;
}

export async function listDocuments(): Promise<DocumentEntry[]> {
  const r = await apiFetch("/documents");
  if (!r.ok) return [];
  const data = await r.json() as { documents: DocumentEntry[] };
  return data.documents ?? [];
}

export async function deleteDocument(filename: string): Promise<void> {
  await apiFetch(`/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
}

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

export async function transcribeAudio(blob: Blob, signal?: AbortSignal): Promise<string> {
  const fd = new FormData();
  const ext = blob.type.includes("ogg") ? "ogg" : "webm";
  fd.append("file", blob, `voice.${ext}`);
  const r = await apiFetch(`/audio/transcribe`, {
    method: "POST",
    body: fd,
    signal,
  });
  if (!r.ok) throw new Error((await r.text()) || `transcribe ${r.status}`);
  const data = (await r.json()) as { text: string };
  return data.text ?? "";
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
  language?: string,
): AsyncGenerator<ChatEvent> {
  const resp = await apiFetch(`/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      message,
      thread_id: threadId,
      conv_id: convId,
      display_currency: displayCurrency,
      language,
    }),
    signal,
  });

  // Plan gate (and any other non-stream error) returns a JSON body, not SSE.
  // Surface the limit message as an error event so the chat UI can react.
  if (!resp.ok) {
    let message = "";
    let limitReached = false;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      const detail = body?.detail;
      if (detail && typeof detail === "object") {
        const d = detail as { error?: string; message?: string };
        limitReached = d.error === "monthly_limit_reached";
        message = d.message ?? "";
      } else if (typeof detail === "string") {
        message = detail;
      }
    } catch {
      /* non-JSON error body — fall through to a generic message */
    }
    yield {
      type: "error",
      payload: { status: resp.status, limitReached, message },
    };
    return;
  }
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

export interface PriceHistory {
  ticker: string;
  currency?: string;
  points: FundHistoryPoint[];
  error?: string;
}

/** Daily close history for any holding (stock/ETF/crypto/index or TEFAS fund). */
export async function priceHistory(
  ticker: string,
  assetClass: string,
  days = 90,
): Promise<PriceHistory> {
  const r = await apiFetch(
    `/insights/history/${encodeURIComponent(ticker)}?days=${days}&asset_class=${encodeURIComponent(assetClass)}`,
  );
  if (!r.ok) return { ticker, points: [], error: `HTTP ${r.status}` };
  return r.json();
}

export interface EightDimResult {
  ticker: string;
  asset_class?: "stock" | "crypto";
  name?: string;
  final_score: number | null;
  recommendation: string | null;
  dimensions: Record<string, { score: number; [k: string]: unknown }>;
  weights: Record<string, number>;
  unavailable_dimensions: string[];
  market_data?: {
    price_usd?: number | null;
    change_pct_24h?: number | null;
    market_cap_usd?: number | null;
    rank?: number | null;
  };
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
  crypto_trending?: { name: string; symbol: string; rank?: number | null; price_usd?: number | null; score?: number | null }[];
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

// ── Short-term crypto signals (4-hour horizon) ──────────────────────────────

export type TradeDirection = "long" | "short" | "neutral";

export interface ShortTermPlan {
  ok: boolean;
  symbol?: string;
  ticker?: string;
  direction?: TradeDirection;
  score?: number;
  confidence?: number;
  confidence_label?: "low" | "medium" | "high";
  horizon_hours?: number;
  entry?: number;
  target?: number | null;
  stop?: number | null;
  target_pct?: number | null;
  stop_pct?: number | null;
  rr?: number | null;
  atr_4h_pct?: number | null;
  grain?: "1h" | "1d";
  components?: { technical: number; derivatives: number; sentiment: number };
  technical_detail?: Record<string, number | null>;
  derivatives_detail?: Record<string, number | string | null>;
  news?: { title: string; source: string; sentiment?: string | null; url?: string }[];
  as_of?: string;
  error?: string;
}

/** Envelope returned by /crypto/short-term/{ticker} — the plan lives in `data`. */
export interface ShortTermSignalResponse {
  ok: boolean;
  formatted_value?: string;
  explanation?: string;
  rationale?: string;
  data?: ShortTermPlan;
  error?: string;
}

export interface CryptoBasketItem {
  symbol: string;
  ticker: string;
  name: string;
}

export async function getCryptoBasket(): Promise<CryptoBasketItem[]> {
  const r = await apiFetch(`/crypto/basket`);
  if (!r.ok) return [];
  const data = (await r.json()) as { basket: CryptoBasketItem[] };
  return data.basket ?? [];
}

export async function getShortTermSignal(ticker: string): Promise<ShortTermSignalResponse> {
  const r = await apiFetch(`/crypto/short-term/${encodeURIComponent(ticker)}`);
  return r.json();
}

export interface TradeTarget {
  id: number;
  ticker: string;
  asset_class: string;
  direction: TradeDirection;
  entry_price: number;
  target_price: number | null;
  stop_price: number | null;
  current_price: number | null;
  pnl_pct: number | null;
  progress: number | null;
  horizon_hours: number;
  confidence: number;
  score: number;
  thesis: string | null;
  status: "active" | "hit" | "stopped" | "expired" | "pending" | "rejected";
  created_at: string | null;
  expires_at: string | null;
  minutes_left: number | null;
  resolved_at: string | null;
  resolved_price: number | null;
}

/** intraday ~4h · swing ~1d · position ~1wk · long ~1mo. */
export type HorizonBucket = "intraday" | "swing" | "position" | "long";

/** Map a stored horizon_hours back to its canonical bucket name (UI labelling). */
export function horizonBucket(hours: number | null | undefined): HorizonBucket {
  if (hours == null) return "swing";
  const buckets: [HorizonBucket, number][] = [
    ["intraday", 4], ["swing", 24], ["position", 168], ["long", 720],
  ];
  return buckets.reduce((best, b) =>
    Math.abs(b[1] - hours) < Math.abs(best[1] - hours) ? b : best
  )[0];
}

export interface TradeTargetsResponse {
  targets: TradeTarget[];
  summary: {
    total: number;
    active: number;
    hit: number;
    stopped: number;
    avg_pnl_pct: number | null;
  };
}

export async function listCryptoTargets(activeOnly = false): Promise<TradeTargetsResponse> {
  const r = await apiFetch(`/crypto/targets${activeOnly ? "?active_only=true" : ""}`);
  if (!r.ok) return { targets: [], summary: { total: 0, active: 0, hit: 0, stopped: 0, avg_pnl_pct: null } };
  return r.json() as Promise<TradeTargetsResponse>;
}

export interface ScanTargetsResponse {
  ok: boolean;
  created: number;
  scanned: number;
  plans: { symbol: string; ok: boolean; formatted_value?: string; plan?: ShortTermPlan; error?: string }[];
}

/** Re-score the whole basket and (re)create a 4-hour target for each tradable coin. */
export async function scanCryptoTargets(): Promise<ScanTargetsResponse> {
  const r = await apiFetch(`/crypto/targets/scan`, { method: "POST" });
  if (!r.ok) return { ok: false, created: 0, scanned: 0, plans: [] };
  return r.json() as Promise<ScanTargetsResponse>;
}

/** Proposed-but-unapproved orders the chat created — awaiting Approve/Reject. */
export async function listPendingTargets(): Promise<TradeTarget[]> {
  const r = await apiFetch(`/crypto/targets/pending`);
  if (!r.ok) return [];
  const data = (await r.json()) as { pending: TradeTarget[] };
  return data.pending ?? [];
}

/** Approve a PENDING proposal → it goes ACTIVE and live-scoring begins. */
export async function confirmTarget(id: number): Promise<{ ok: boolean; target?: TradeTarget; error?: string }> {
  const r = await apiFetch(`/crypto/targets/${id}/confirm`, { method: "POST" });
  return r.json();
}

/** Decline a PENDING proposal. */
export async function rejectTarget(id: number): Promise<{ ok: boolean; error?: string }> {
  const r = await apiFetch(`/crypto/targets/${id}/reject`, { method: "POST" });
  return r.json();
}

/** One (horizon × asset-class) cell of the evaluation scorecard. */
export interface ScorecardCell {
  horizon: string;
  asset_class: string;
  n_resolved: number;
  n_returns: number;
  avg_return_pct: number | null;
  total_return_pct: number | null;
  hit_rate: number | null;
  profit_factor: number | null;
  sharpe: number | null;
  sharpe_annualized: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown_pct: number | null;
  brier: number | null;
  ece: number | null;
  psr: number | null;
  dsr: number | null;
  purged_kfold: { folds: number; mean: number; std: number } | null;
  avg_confidence: number | null;
}

export interface ScorecardResponse {
  ok: boolean;
  n_total: number;
  n_resolved: number;
  n_cells: number;
  overall: ScorecardCell;
  by_cell: ScorecardCell[];
  notes: string;
  error?: string;
}

/** Research-grounded "jury" scorecard over the user's resolved trade targets. */
export async function getScorecard(): Promise<ScorecardResponse | null> {
  const r = await apiFetch(`/eval/scorecard`);
  if (!r.ok) return null;
  return r.json() as Promise<ScorecardResponse>;
}

// ── Quant Lab (backend/app/quant) ──────────────────────────────────────────

/** Summary produced by `app.quant.backtest.summarize`. */
export interface BacktestMetrics {
  n_bars: number;
  insufficient_data?: boolean;
  total_return_pct: number | null;
  gross_return_pct: number | null;
  benchmark_return_pct: number | null;
  excess_vs_buy_hold_pct: number | null;
  cagr_pct: number | null;
  ann_vol_pct: number | null;
  sharpe: number | null;
  sharpe_annualized: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown_pct: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  psr: number | null;
  dsr: number | null;
  n_trials: number;
  n_trades: number;
  turnover: number | null;
  cost_drag_pct: number | null;
}

export interface WalkForwardFold {
  fold: number;
  train_bars: number;
  test_bars: number;
  params: Record<string, number>;
  train_sharpe: number | null;
  test_sharpe: number | null;
  test_return_pct: number;
}

/** Out-of-sample validation block; `ok: false` carries the reason it was skipped. */
export interface WalkForwardResult {
  ok: boolean;
  reason?: string;
  n_folds?: number;
  n_trials?: number;
  embargo_bars?: number;
  oos_bars?: number;
  oos_return_pct?: number;
  oos_sharpe?: number | null;
  oos_sharpe_annualized?: number | null;
  oos_sortino?: number | null;
  oos_max_drawdown_pct?: number | null;
  oos_dsr?: number | null;
  folds?: WalkForwardFold[];
  note?: string;
}

export interface BacktestRequest {
  ticker: string;
  strategy?: string;
  period_days?: number;
  fast?: number;
  slow?: number;
  lookback?: number;
  fee_bps?: number;
  slippage_bps?: number;
  allow_short?: boolean;
  walk_forward?: boolean;
}

export interface BacktestResponse {
  ok: boolean;
  error?: string;
  ticker?: string;
  strategy?: string;
  params?: Record<string, number>;
  costs?: { fee_bps: number; slippage_bps: number };
  dates?: string[];
  /** Full-resolution curves — the page has no SSE size cap to respect. */
  equity?: number[];
  benchmark?: number[];
  drawdown?: number[];
  positions?: number[];
  metrics?: BacktestMetrics;
  walk_forward?: WalkForwardResult | null;
}

export interface StrategyInfo {
  key: string;
  grid: Record<string, (number | string)[]>;
  n_combinations: number;
}

export interface FrontierPoint {
  vol_pct: number;
  return_pct: number;
  sharpe?: number;
}

export interface WeightChange {
  ticker: string;
  current_pct: number;
  target_pct: number;
  change_pct: number;
}

export interface OptimizeResponse {
  ok: boolean;
  error?: string;
  explanation?: string;
  formatted_value?: string;
  objective?: string;
  currency?: string;
  shrinkage?: number;
  converged?: boolean;
  points?: FrontierPoint[];
  current?: FrontierPoint & { label: string };
  optimal?: FrontierPoint & { label: string };
  bars?: { label: string; value: number }[];
  changes?: WeightChange[];
}

export interface QuantRiskResponse {
  ok: boolean;
  error?: string;
  currency?: string;
  n_obs?: number;
  confidence?: number;
  weights?: { label: string; value: number }[];
  var_pct?: number;
  cvar_pct?: number;
  cornish_fisher_var_pct?: number | null;
  ewma_vol_pct?: number | null;
  worst_day_pct?: number;
  max_drawdown_pct?: number;
  drawdown_curve?: number[];
  benchmark?: string;
  benchmark_stats?: {
    n_obs: number;
    beta: number;
    alpha_annualized_pct: number;
    r2: number | null;
    beta_t_stat: number | null;
    beta_p_value: number;
    correlation: number | null;
    idiosyncratic_vol_pct: number;
    tracking_error_pct: number;
  } | null;
  capture?: { up_capture_pct: number | null; down_capture_pct: number | null } | null;
}

/** Strategy catalogue — drives the Quant Lab picker and shows each search width. */
export async function getQuantStrategies(): Promise<StrategyInfo[]> {
  const r = await apiFetch(`/quant/strategies`);
  if (!r.ok) return [];
  const body = (await r.json()) as { ok: boolean; strategies?: StrategyInfo[] };
  return body.strategies ?? [];
}

/** Full-resolution backtest, optionally with walk-forward validation. */
export async function runBacktest(req: BacktestRequest): Promise<BacktestResponse> {
  const r = await apiFetch(`/quant/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json() as Promise<BacktestResponse>;
}

/** Efficient frontier + optimal weights over the user's real holdings. */
export async function optimizePortfolio(req: {
  objective?: string;
  period_days?: number;
  long_only?: boolean;
  max_weight_pct?: number;
}): Promise<OptimizeResponse> {
  const r = await apiFetch(`/quant/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json() as Promise<OptimizeResponse>;
}

/** Portfolio tail risk + benchmark regression. */
export async function getQuantRisk(
  periodDays = 365, confidence = 0.95, benchmark = "SPY",
): Promise<QuantRiskResponse> {
  const params = new URLSearchParams({
    period_days: String(periodDays),
    confidence: String(confidence),
    benchmark,
  });
  const r = await apiFetch(`/quant/risk?${params}`);
  return r.json() as Promise<QuantRiskResponse>;
}

/** Read-only multi-asset, horizon-aware trade signal (no order placed). */
export async function getTradeSignal(
  symbol: string, horizon: HorizonBucket = "swing", assetClass = "",
): Promise<ShortTermSignalResponse> {
  const params = new URLSearchParams({ horizon });
  if (assetClass) params.set("asset_class", assetClass);
  const r = await apiFetch(`/crypto/signal/${encodeURIComponent(symbol)}?${params}`);
  return r.json();
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
