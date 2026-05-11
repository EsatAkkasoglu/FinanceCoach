/**
 * StepFinances — onboarding step 3
 *
 * Three modes for collecting account + income info:
 *  1. Manual  — add income sources and accounts one by one
 *  2. Upload  — drop a bank statement / payslip / invoice → AI extracts
 *  3. Describe — write in plain language → AI extracts (sent as text blob)
 *
 * Income sources and accounts are always shown as persistent lists below the panel.
 */
import { useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pencil, Upload, MessageSquare, Plus, Trash2, Loader2,
  CheckCircle2, AlertCircle, TrendingUp, Building2, DollarSign, Briefcase, Home,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { parseDocument, type ProfileExtraction } from "@/lib/api";
import type { AccountKind } from "@/lib/api";

// ── Shared types ──────────────────────────────────────────────────────────────

export interface AccountDraft {
  name: string;
  kind: AccountKind;
  balance: number;
  currency: string;
  institution: string;
}

export interface IncomeDraft {
  label: string;
  amount: number;
  currency: string;
  category?: string; // "salary", "subscription", "rental", "freelance", "other"
}

export interface FinancesDraft {
  monthlyIncome: number;   // kept in sync = sum of incomeSources
  accounts: AccountDraft[];
  incomeSources: IncomeDraft[];
}

interface Props {
  value: FinancesDraft;
  onChange: (patch: Partial<FinancesDraft>) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

type Mode = "manual" | "upload" | "describe";

const MODES: { key: Mode; icon: typeof Pencil; label: string; desc: string }[] = [
  { key: "manual",   icon: Pencil,        label: "Enter manually",    desc: "Add income sources and accounts" },
  { key: "upload",   icon: Upload,        label: "Upload a document", desc: "Bank statement, payslip or invoice" },
  { key: "describe", icon: MessageSquare, label: "Describe it",       desc: "Plain language — AI understands" },
];

const KIND_LABELS: Record<AccountKind, string> = {
  cash: "Cash / Wallet",
  checking: "Checking",
  savings: "Savings",
  credit_card: "Credit card",
};

const CURRENCIES = ["TRY", "USD", "EUR", "GBP"];

// Group income by currency and sum within each group
function groupIncomeByCurrency(sources: IncomeDraft[]): Record<string, number> {
  return sources.reduce((acc, src) => {
    acc[src.currency] = (acc[src.currency] || 0) + src.amount;
    return acc;
  }, {} as Record<string, number>);
}

// Format income summary by currency
function formatIncomeSummary(sources: IncomeDraft[]): string {
  const grouped = groupIncomeByCurrency(sources);
  return Object.entries(grouped)
    .map(([currency, amount]) => `${amount.toLocaleString()} ${currency}`)
    .join(", ");
}

// Get primary currency (most common or first)
function getPrimaryCurrency(sources: IncomeDraft[]): string {
  if (sources.length === 0) return "TRY";
  const grouped = groupIncomeByCurrency(sources);
  return Object.keys(grouped)[0] || "TRY";
}

// Get total for primary currency (for validation)
function sumIncome(sources: IncomeDraft[]): number {
  const grouped = groupIncomeByCurrency(sources);
  const primary = getPrimaryCurrency(sources);
  return grouped[primary] || 0;
}

// ── Root component ────────────────────────────────────────────────────────────

export function StepFinances({ value, onChange }: Props) {
  const [mode, setMode] = useState<Mode>("manual");
  const [extraction, setExtraction] = useState<ProfileExtraction | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);

  function addIncomeSource(src: IncomeDraft) {
    const next = [...value.incomeSources, src];
    onChange({ incomeSources: next, monthlyIncome: sumIncome(next) });
  }

  function removeIncomeSource(i: number) {
    const next = value.incomeSources.filter((_, idx) => idx !== i);
    onChange({ incomeSources: next, monthlyIncome: sumIncome(next) });
  }

  function addAccount(acc: AccountDraft) {
    onChange({ accounts: [...value.accounts, acc] });
  }

  function removeAccount(i: number) {
    onChange({ accounts: value.accounts.filter((_, idx) => idx !== i) });
  }

  function acceptExtraction(selected: IncomeDraft[]) {
    const next = [...value.incomeSources, ...selected];
    onChange({ incomeSources: next, monthlyIncome: sumIncome(next) });
    setExtraction(null);
  }

  const totalMonthly = value.incomeSources.length > 0
    ? sumIncome(value.incomeSources)
    : value.monthlyIncome;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Your finances</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          Tell me about your accounts and income — I'll set up your budget automatically.
        </p>
      </div>

      {/* Mode switcher */}
      <div className="grid grid-cols-3 gap-2">
        {MODES.map(({ key, icon: Icon, label, desc }) => (
          <button
            key={key}
            type="button"
            onClick={() => { setMode(key); setExtraction(null); setExtractError(null); }}
            className={cn(
              "flex flex-col items-start gap-1.5 rounded-xl border p-3 text-left transition",
              mode === key
                ? "border-accent bg-accent/10 shadow-glow"
                : "border-[hsl(var(--border))] hover:border-accent/50 hover:bg-[hsl(var(--surface-2))]"
            )}
          >
            <Icon className={cn("h-4 w-4", mode === key ? "text-accent" : "text-[hsl(var(--text-muted))]")} />
            <span className="text-xs font-medium leading-tight">{label}</span>
            <span className="text-[10px] leading-tight text-[hsl(var(--text-muted))]">{desc}</span>
          </button>
        ))}
      </div>

      {/* Mode panels */}
      <AnimatePresence mode="wait">
        <motion.div
          key={mode}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.18 }}
        >
          {mode === "manual" && (
            <ManualPanel onAddIncome={addIncomeSource} onAddAccount={addAccount} />
          )}
          {mode === "upload" && (
            <UploadPanel
              extracting={extracting}
              setExtracting={setExtracting}
              setExtraction={setExtraction}
              setExtractError={setExtractError}
            />
          )}
          {mode === "describe" && (
            <DescribePanel
              extracting={extracting}
              setExtracting={setExtracting}
              setExtraction={setExtraction}
              setExtractError={setExtractError}
            />
          )}
        </motion.div>
      </AnimatePresence>

      {/* Extraction result */}
      <AnimatePresence>
        {extraction && (
          <ExtractionPreview
            extraction={extraction}
            onAccept={acceptExtraction}
            onDiscard={() => setExtraction(null)}
          />
        )}
      </AnimatePresence>

      {extractError && (
        <div className="flex items-start gap-2 rounded-lg border border-loss/40 bg-loss/10 px-3 py-2 text-xs text-loss">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {extractError}
        </div>
      )}

      {/* ── Persistent lists ── */}

      {/* Income sources list */}
      {value.incomeSources.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Income sources
            </p>
            <span className="num text-xs font-semibold text-gain">
              {formatIncomeSummary(value.incomeSources)} / month
            </span>
          </div>
          <ul className="space-y-1.5">
            {value.incomeSources.map((src, i) => (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <TrendingUp className="h-3.5 w-3.5 shrink-0 text-gain" />
                  <span className="truncate font-medium">{src.label}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="num font-semibold text-gain">
                    {src.amount.toLocaleString()} {src.currency}
                  </span>
                  <button type="button" onClick={() => removeIncomeSource(i)} className="text-[hsl(var(--text-muted))] hover:text-loss">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </motion.li>
            ))}
          </ul>
        </div>
      )}

      {/* Accounts list */}
      {value.accounts.length > 0 && (
        <div>
          <p className="mb-2 text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
            Accounts ({value.accounts.length})
          </p>
          <ul className="space-y-1.5">
            {value.accounts.map((acc, i) => (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Building2 className="h-3.5 w-3.5 shrink-0 text-[hsl(var(--text-muted))]" />
                  <div className="min-w-0">
                    <span className="font-medium">{acc.name}</span>
                    <span className="ml-1.5 text-[hsl(var(--text-muted))]">{KIND_LABELS[acc.kind]}</span>
                    {acc.institution && <span className="ml-1 text-[hsl(var(--text-muted))]">· {acc.institution}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="num font-semibold">{acc.balance.toLocaleString()} {acc.currency}</span>
                  <button type="button" onClick={() => removeAccount(i)} className="text-[hsl(var(--text-muted))] hover:text-loss">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </motion.li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Manual panel ──────────────────────────────────────────────────────────────

function ManualPanel({
  onAddIncome,
  onAddAccount,
}: {
  onAddIncome: (src: IncomeDraft) => void;
  onAddAccount: (acc: AccountDraft) => void;
}) {
  const [incomeForm, setIncomeForm] = useState<{ open: boolean; label: string; amount: number; currency: string }>({
    open: false, label: "", amount: 0, currency: "TRY",
  });
  const [accountForm, setAccountForm] = useState<{ open: boolean } & AccountDraft>({
    open: false, name: "", kind: "checking", balance: 0, currency: "TRY", institution: "",
  });

  function submitIncome() {
    if (!incomeForm.label.trim() || incomeForm.amount <= 0) return;
    onAddIncome({ label: incomeForm.label.trim(), amount: incomeForm.amount, currency: incomeForm.currency });
    setIncomeForm({ open: false, label: "", amount: 0, currency: "TRY" });
  }

  function submitAccount() {
    if (!accountForm.name.trim()) return;
    onAddAccount({ name: accountForm.name.trim(), kind: accountForm.kind, balance: accountForm.balance, currency: accountForm.currency, institution: accountForm.institution });
    setAccountForm({ open: false, name: "", kind: "checking", balance: 0, currency: "TRY", institution: "" });
  }

  return (
    <div className="space-y-3">
      {/* Income source form */}
      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Income sources</span>
          <button type="button" onClick={() => setIncomeForm((f) => ({ ...f, open: !f.open }))}
            className="flex items-center gap-1 text-xs text-accent hover:underline">
            <Plus className="h-3 w-3" /> Add income
          </button>
        </div>
        <AnimatePresence>
          {incomeForm.open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-2 overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4 space-y-3"
            >
              <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Source name</span>
                <input
                  autoFocus
                  value={incomeForm.label}
                  onChange={(e) => setIncomeForm((f) => ({ ...f, label: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && submitIncome()}
                  placeholder="Salary, freelance, rent income…"
                  className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Monthly amount</span>
                  <input
                    type="number" min={0} step={100}
                    value={incomeForm.amount || ""}
                    onChange={(e) => setIncomeForm((f) => ({ ...f, amount: Number(e.target.value) }))}
                    onKeyDown={(e) => e.key === "Enter" && submitIncome()}
                    placeholder="15 000"
                    className="num mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent"
                  />
                </label>
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Currency</span>
                  <select value={incomeForm.currency} onChange={(e) => setIncomeForm((f) => ({ ...f, currency: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent">
                    {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setIncomeForm((f) => ({ ...f, open: false }))}
                  className="rounded-lg px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]">Cancel</button>
                <button type="button" onClick={submitIncome}
                  disabled={!incomeForm.label.trim() || incomeForm.amount <= 0}
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-40">Add</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Account form */}
      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Accounts</span>
          <button type="button" onClick={() => setAccountForm((f) => ({ ...f, open: !f.open }))}
            className="flex items-center gap-1 text-xs text-accent hover:underline">
            <Plus className="h-3 w-3" /> Add account
          </button>
        </div>
        <AnimatePresence>
          {accountForm.open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-2 overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4 space-y-3"
            >
              <label className="block">
                <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Account name</span>
                <input
                  autoFocus
                  value={accountForm.name}
                  onChange={(e) => setAccountForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Ziraat maaş hesabı"
                  className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Type</span>
                  <select value={accountForm.kind} onChange={(e) => setAccountForm((f) => ({ ...f, kind: e.target.value as AccountKind }))}
                    className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent">
                    {Object.entries(KIND_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Institution</span>
                  <input value={accountForm.institution}
                    onChange={(e) => setAccountForm((f) => ({ ...f, institution: e.target.value }))}
                    placeholder="Garanti, Ziraat…"
                    className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent" />
                </label>
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Balance</span>
                  <input type="number" min={0} value={accountForm.balance || ""}
                    onChange={(e) => setAccountForm((f) => ({ ...f, balance: Number(e.target.value) }))}
                    placeholder="50 000"
                    className="num mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent" />
                </label>
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Currency</span>
                  <select value={accountForm.currency} onChange={(e) => setAccountForm((f) => ({ ...f, currency: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-sm outline-none focus:border-accent">
                    {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setAccountForm((f) => ({ ...f, open: false }))}
                  className="rounded-lg px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]">Cancel</button>
                <button type="button" onClick={submitAccount}
                  disabled={!accountForm.name.trim()}
                  className="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-accent-fg disabled:opacity-40">Add</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ── Upload panel ──────────────────────────────────────────────────────────────

interface ExtractPanelProps {
  extracting: boolean;
  setExtracting: (v: boolean) => void;
  setExtraction: (ex: ProfileExtraction | null) => void;
  setExtractError: (e: string | null) => void;
}

function UploadPanel({ extracting, setExtracting, setExtraction, setExtractError }: ExtractPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  async function handleFile(file: File) {
    setFileName(file.name);
    setExtractError(null);
    setExtracting(true);
    try {
      const result = await parseDocument(file);
      setExtraction(result);
    } catch (err) {
      setExtractError((err as Error).message || "Could not parse document. Try another file.");
    } finally {
      setExtracting(false);
    }
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
      onClick={() => !extracting && inputRef.current?.click()}
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed py-8 transition cursor-pointer",
        dragOver ? "border-accent bg-accent/10" : "border-[hsl(var(--border))] hover:border-accent/50",
        extracting && "pointer-events-none opacity-60"
      )}
    >
      <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.csv" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
      {extracting ? (
        <>
          <Loader2 className="h-8 w-8 animate-spin text-accent" />
          <p className="text-sm text-[hsl(var(--text-muted))]">Analyzing {fileName}…</p>
        </>
      ) : (
        <>
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[hsl(var(--surface-2))]">
            <Upload className="h-5 w-5 text-[hsl(var(--text-muted))]" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium">Drop a file or click to browse</p>
            <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">PDF · PNG · JPG · CSV</p>
          </div>
          {fileName && <span className="text-xs text-gain">✓ {fileName} processed — check results below</span>}
        </>
      )}
    </div>
  );
}

// ── Describe panel ────────────────────────────────────────────────────────────

function DescribePanel({ extracting, setExtracting, setExtraction, setExtractError }: ExtractPanelProps) {
  const [text, setText] = useState("");

  async function handleExtract() {
    if (!text.trim()) return;
    setExtractError(null);
    setExtracting(true);
    try {
      const blob = new Blob([text.trim()], { type: "text/plain" });
      const file = new File([blob], "description.txt", { type: "text/plain" });
      const result = await parseDocument(file);
      setExtraction(result);
    } catch (err) {
      setExtractError((err as Error).message || "Couldn't understand that. Try being more specific.");
    } finally {
      setExtracting(false);
    }
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-1 text-xs text-[hsl(var(--text-muted))] list-disc list-inside">
        <li>"Garanti Bank checking, ₺45,000 balance, salary ₺22,000/month"</li>
        <li>"Ziraat maaş hesabı 50.000 TL, kira geliri 5.000 TL/ay"</li>
      </ul>
      <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Describe your accounts, income sources and balances…"
        rows={4}
        className="w-full resize-none rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-sm outline-none focus:border-accent" />
      <button type="button" onClick={handleExtract} disabled={!text.trim() || extracting}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent py-2.5 text-sm font-medium text-accent-fg disabled:opacity-40">
        {extracting
          ? <><Loader2 className="h-4 w-4 animate-spin" /> Analyzing…</>
          : <><MessageSquare className="h-4 w-4" /> Let AI read this</>}
      </button>
    </div>
  );
}

// ── Extraction preview ────────────────────────────────────────────────────────

function ExtractionPreview({
  extraction,
  onAccept,
  onDiscard,
}: {
  extraction: ProfileExtraction;
  onAccept: (selected: IncomeDraft[]) => void;
  onDiscard: () => void;
}) {
  const profile = extraction.suggested_profile;

  // Build candidate income items from transactions (with detailed descriptions)
  const incomeTransactions = extraction.suggested_transactions
    .filter((t) => t.type === "income" && t.amount != null)
    .map((t) => {
      // If category is missing, infer from description
      let inferredCategory = t.category?.toLowerCase() ?? "other";
      if (!t.category && t.description) {
        const desc = t.description.toLowerCase();
        if (desc.includes("salary") || desc.includes("wage") || desc.includes("paycheck")) inferredCategory = "salary";
        else if (desc.includes("youtube") || desc.includes("patreon") || desc.includes("subscription") || desc.includes("affiliate")) inferredCategory = "subscription";
        else if (desc.includes("rent") || desc.includes("rental") || desc.includes("lease")) inferredCategory = "rental";
        else if (desc.includes("freelance") || desc.includes("contract") || desc.includes("consulting")) inferredCategory = "freelance";
      }
      return {
        label: t.description || `${t.category || "Income"}${t.category ? ` income` : ""}`,
        amount: t.amount!,
        currency: t.currency ?? "TRY",
        category: inferredCategory,
      };
    });

  // Fall back to profile.monthly_income only if no transactions were extracted
  const fallbackIncome = incomeTransactions.length === 0 && profile?.monthly_income != null
    ? [{ label: "Monthly income", amount: profile.monthly_income, currency: profile.currency ?? "TRY", category: "other" }]
    : [];

  const candidates: IncomeDraft[] = [...incomeTransactions, ...fallbackIncome];

  // De-duplicate by amount+currency
  const unique = candidates.filter(
    (c, i, arr) => arr.findIndex((x) => x.amount === c.amount && x.currency === c.currency) === i
  );

  const [checked, setChecked] = useState<boolean[]>(() => unique.map(() => true));

  const docLabel: Record<string, string> = {
    bank_statement: "Bank statement", salary_slip: "Payslip",
    invoice: "Invoice", receipt: "Receipt", broker_statement: "Broker statement",
    portfolio_screenshot: "Portfolio screenshot", other: "Document",
  };

  const selectedItems = unique.filter((_, i) => checked[i]);
  const selectedTotal = selectedItems.reduce((s, x) => s + x.amount, 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
      className="rounded-xl border border-gain/40 bg-gain/10 p-4 space-y-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-gain mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{docLabel[extraction.doc_type] ?? "Document"} analyzed</p>
          <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))] line-clamp-2">{extraction.summary}</p>
        </div>
        {extraction.suggested_transactions.length > 0 && (
          <span className="shrink-0 rounded-full bg-[hsl(var(--surface-2))] px-2 py-0.5 text-[10px] text-[hsl(var(--text-muted))]">
            {extraction.suggested_transactions.length} tx
          </span>
        )}
      </div>

      {/* Income selection */}
      {unique.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[hsl(var(--text))]">
            Select income sources to add to your profile:
          </p>
          <div className="space-y-1.5">
            {unique.map((item, i) => {
              const catIcon = item.category === "salary" ? DollarSign
                : item.category === "subscription" ? Briefcase
                : item.category === "rental" ? Home
                : TrendingUp;
              const CatIcon = catIcon;
              const catLabel = item.category === "salary" ? "Salary"
                : item.category === "subscription" ? "Subscription"
                : item.category === "rental" ? "Rental income"
                : item.category === "freelance" ? "Freelance"
                : "Other income";

              return (
                <label
                  key={i}
                  className={cn(
                    "flex cursor-pointer items-center justify-between rounded-lg border px-3 py-3 transition",
                    checked[i]
                      ? "border-accent bg-accent/10"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] opacity-60"
                  )}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <input
                      type="checkbox"
                      checked={checked[i]}
                      onChange={() => setChecked((prev) => prev.map((v, idx) => idx === i ? !v : v))}
                      className="h-3.5 w-3.5 accent-[hsl(var(--accent))]"
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <CatIcon className={cn("h-3 w-3 shrink-0", checked[i] ? "text-gain" : "text-[hsl(var(--text-muted))]")} />
                        <span className={cn("truncate text-xs font-medium", checked[i] ? "text-[hsl(var(--text))]" : "text-[hsl(var(--text-muted))]")}>
                          {item.label}
                        </span>
                      </div>
                      <span className="text-[10px] text-[hsl(var(--text-muted))] mt-0.5 block">{catLabel}</span>
                    </div>
                  </div>
                  <span className={cn("num ml-3 shrink-0 text-xs font-semibold whitespace-nowrap", checked[i] ? "text-gain" : "text-[hsl(var(--text-muted))]")}>
                    {item.amount.toLocaleString()} {item.currency}/mo
                  </span>
                </label>
              );
            })}
          </div>
          {selectedItems.length > 1 && (
            <p className="text-right text-xs text-[hsl(var(--text-muted))]">
              Total: <span className="num font-semibold text-gain">{selectedTotal.toLocaleString()} / month</span>
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-[hsl(var(--text-muted))]">
          No income found — add income manually using the form above.
        </p>
      )}

      {extraction.follow_up_questions.length > 0 && (
        <p className="text-[10px] text-[hsl(var(--text-muted))] italic">💡 {extraction.follow_up_questions[0]}</p>
      )}

      <div className="flex gap-2">
        <button type="button" onClick={() => onAccept(selectedItems)}
          disabled={unique.length > 0 && selectedItems.length === 0}
          className="flex-1 rounded-lg bg-accent py-2 text-xs font-medium text-accent-fg disabled:opacity-40">
          {selectedItems.length > 0
            ? `Add ${selectedItems.length} income source${selectedItems.length > 1 ? "s" : ""} to my profile`
            : "Apply without income"}
        </button>
        <button type="button" onClick={onDiscard}
          className="rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]">
          Discard
        </button>
      </div>
    </motion.div>
  );
}
