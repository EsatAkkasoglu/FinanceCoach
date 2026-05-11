/**
 * Budget-context document import. Drops PDFs / images / docs onto Gemini,
 * lets the user review what was extracted, and writes selected rows to
 * /transactions/bulk (and /portfolio/holdings if any investments showed up).
 */
import { useEffect, useRef, useState } from "react";
import {
  Upload, FileText, X, AlertTriangle, CheckCircle2, Sparkles, Loader2,
  ArrowRight, TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import {
  parseDocument, createTransactionsBulk, addHolding, updateProfile,
  type ProfileExtraction, type TransactionSuggestion, type HoldingSuggestion,
  type Account, type TransactionInput,
} from "@/lib/api";
import { cn } from "@/lib/cn";

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
  accounts: Account[];
}

const ACCEPTED = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.csv";
const MAX_BYTES = 50 * 1024 * 1024;

const STAGES = [
  { key: "uploading", label: "Uploading file" },
  { key: "analyzing", label: "AI is reading the document" },
  { key: "preparing", label: "Preparing suggestions" },
] as const;

type Stage = (typeof STAGES)[number]["key"];
type Step = "pick" | "loading" | "review";

const DOC_TYPE_LABELS: Record<ProfileExtraction["doc_type"], string> = {
  bank_statement: "Bank statement",
  broker_statement: "Broker statement",
  portfolio_screenshot: "Portfolio screenshot",
  invoice: "Invoice",
  receipt: "Receipt",
  id_document: "ID document",
  salary_slip: "Salary slip",
  other: "Document",
};

export function BudgetImportModal({ open, onClose, onImported, accounts }: Props) {
  const [step, setStep] = useState<Step>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<Stage>("uploading");
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ProfileExtraction | null>(null);

  // Selection state
  const [selectedTxs, setSelectedTxs] = useState<Set<number>>(new Set());
  const [selectedHoldings, setSelectedHoldings] = useState<Set<number>>(new Set());
  const [acceptName, setAcceptName] = useState(true);
  const [acceptIncome, setAcceptIncome] = useState(true);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const stageTimerRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setStep("pick");
    setFile(null);
    setStage("uploading");
    setError(null);
    setExtraction(null);
    setSelectedTxs(new Set());
    setSelectedHoldings(new Set());
    setAcceptName(true);
    setAcceptIncome(true);
    setAccountId(accounts[0]?.id ?? null);
    setImporting(false);
    abortRef.current?.abort();
    if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
  }

  useEffect(() => {
    if (!open) reset();
    return () => {
      abortRef.current?.abort();
      if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function pickFile(f: File) {
    setError(null);
    if (f.size > MAX_BYTES) {
      setError(`File is too large (${formatBytes(f.size)}). Max 50 MB.`);
      return;
    }
    setFile(f);
  }

  async function startParsing() {
    if (!file) return;
    setStep("loading");
    setStage("uploading");
    setError(null);

    if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
    stageTimerRef.current = window.setTimeout(() => setStage("analyzing"), 700);
    const t2 = window.setTimeout(() => setStage("preparing"), 4500);

    abortRef.current = new AbortController();
    try {
      const result = await parseDocument(file, abortRef.current.signal);
      window.clearTimeout(t2);
      if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
      setExtraction(result);
      // Default-select every transaction with the data we need.
      setSelectedTxs(new Set(
        result.suggested_transactions
          .map((t, i) => isCompleteTx(t) ? i : -1)
          .filter((i) => i >= 0),
      ));
      setSelectedHoldings(new Set(result.suggested_holdings.map((_, i) => i)));
      setStep("review");
    } catch (err) {
      window.clearTimeout(t2);
      if ((err as Error).name === "AbortError") return;
      setError((err as Error).message || "Failed to read document");
      setStep("pick");
    }
  }

  async function handleImport() {
    if (!extraction) return;
    setImporting(true);

    let txCreated = 0;
    let holdingCreated = 0;

    // Transactions
    const txItems: TransactionInput[] = Array.from(selectedTxs)
      .map((i) => extraction.suggested_transactions[i])
      .filter(isCompleteTx)
      .map((t) => ({
        occurred_on: t.occurred_on as string,
        type: t.type === "transfer" || t.type === "unknown"
          ? (t.amount! < 0 ? "expense" : "income")
          : t.type,
        amount: Math.abs(t.amount!),
        currency: t.currency || "TRY",
        category: t.category || "uncategorized",
        description: t.description ?? "",
        source: "upload",
        account_id: accountId,
      }));
    if (txItems.length > 0) {
      try {
        const r = await createTransactionsBulk(txItems);
        txCreated = r.created;
      } catch (err) {
        toast.error(`Failed to import transactions: ${(err as Error).message}`);
      }
    }

    // Holdings — secondary action
    for (const i of selectedHoldings) {
      const h = extraction.suggested_holdings[i];
      if (!h?.quantity || h.quantity <= 0) continue;
      try {
        await addHolding({
          ticker: h.ticker,
          quantity: h.quantity,
          cost_basis: h.cost_basis ?? 0,
          asset_class: h.asset_class,
        });
        holdingCreated++;
      } catch { /* keep going */ }
    }

    // Profile updates
    const profile = extraction.suggested_profile;
    if (profile) {
      const patch: Record<string, unknown> = {};
      if (acceptName && profile.name) patch.name = profile.name;
      if (acceptIncome && profile.monthly_income != null) patch.monthly_income = profile.monthly_income;
      if (Object.keys(patch).length > 0) {
        try { await updateProfile(patch); } catch { /* non-fatal */ }
      }
    }

    setImporting(false);
    const parts: string[] = [];
    if (txCreated) parts.push(`${txCreated} transaction${txCreated === 1 ? "" : "s"}`);
    if (holdingCreated) parts.push(`${holdingCreated} holding${holdingCreated === 1 ? "" : "s"}`);
    if (parts.length) toast.success(`Imported ${parts.join(" and ")}`);
    else toast.success("Profile updated");
    onImported();
    onClose();
  }

  // ── Render ────────────────────────────────────────────────────────────

  const title = step === "review" ? "Review what we found" : "Import a document";
  const description =
    step === "review"
      ? "Pick what to add to your budget. You can edit anything afterwards."
      : "Drop a bank statement, receipt, payslip — anything financial. AI extracts transactions and routes them. Files aren't stored.";

  return (
    <Modal
      open={open}
      onClose={() => { if (!importing) onClose(); }}
      title={title}
      description={description}
      size="lg"
      footer={renderFooter()}
    >
      {step === "pick" && (
        <PickStep file={file} error={error} onPick={pickFile}
          onClear={() => setFile(null)} fileInputRef={fileInputRef} />
      )}
      {step === "loading" && <LoadingStep stage={stage} filename={file?.name ?? ""} />}
      {step === "review" && extraction && (
        <ReviewStep
          extraction={extraction}
          selectedTxs={selectedTxs}
          toggleTx={(i) => toggle(setSelectedTxs, i)}
          selectedHoldings={selectedHoldings}
          toggleHolding={(i) => toggle(setSelectedHoldings, i)}
          acceptName={acceptName}
          setAcceptName={setAcceptName}
          acceptIncome={acceptIncome}
          setAcceptIncome={setAcceptIncome}
          accounts={accounts}
          accountId={accountId}
          setAccountId={setAccountId}
          onPickAnother={() => reset()}
        />
      )}
    </Modal>
  );

  function renderFooter() {
    if (step === "pick") {
      return (
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={startParsing} disabled={!file}>
            Analyze <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </>
      );
    }
    if (step === "loading") {
      return (
        <Button variant="ghost" onClick={() => { abortRef.current?.abort(); reset(); }}>
          Cancel
        </Button>
      );
    }
    const total =
      selectedTxs.size + selectedHoldings.size
      + (acceptName && extraction?.suggested_profile?.name ? 1 : 0)
      + (acceptIncome && extraction?.suggested_profile?.monthly_income != null ? 1 : 0);
    return (
      <>
        <Button variant="ghost" onClick={() => reset()}>Pick another file</Button>
        <Button onClick={handleImport} loading={importing} disabled={total === 0}>
          {total === 0 ? "Nothing selected" : `Import ${total} item${total === 1 ? "" : "s"}`}
        </Button>
      </>
    );
  }
}

// Helpers + sub-components

function toggle<T>(setter: (fn: (s: Set<T>) => Set<T>) => void, key: T) {
  setter((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
}

function isCompleteTx(t: TransactionSuggestion): boolean {
  return Boolean(t.occurred_on && t.amount && t.amount !== 0);
}

function PickStep({
  file, error, onPick, onClear, fileInputRef,
}: {
  file: File | null;
  error: string | null;
  onPick: (f: File) => void;
  onClear: () => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
}) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files[0];
          if (f) onPick(f);
        }}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-8 py-12 text-center transition",
          dragOver
            ? "border-accent bg-accent/5"
            : "border-[hsl(var(--border))] hover:border-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))]",
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-muted">
          <Upload className="h-5 w-5 text-accent" />
        </div>
        <p className="text-sm font-medium">Drop a file here, or click to browse</p>
        <p className="text-xs text-[hsl(var(--text-muted))]">Bank statements · receipts · payslips · screenshots — up to 50 MB</p>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPick(f);
            e.target.value = "";
          }}
        />
      </div>

      {file && (
        <div className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2.5">
          <FileText className="h-4 w-4 shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-[hsl(var(--text-muted))]">{formatBytes(file.size)}</p>
          </div>
          <button onClick={(e) => { e.stopPropagation(); onClear(); }}
            className="rounded p-1 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface))] hover:text-loss"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-loss/40 bg-loss/10 p-3 text-xs text-loss">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <p className="rounded-lg bg-[hsl(var(--surface-2))]/60 px-3 py-2 text-[11px] text-[hsl(var(--text-muted))]">
        🔒 Files go to Gemini for analysis only. Nothing is stored on our side right now.
      </p>
    </div>
  );
}

function LoadingStep({ stage, filename }: { stage: Stage; filename: string }) {
  return (
    <div className="py-8">
      <p className="mb-6 truncate text-center text-xs text-[hsl(var(--text-muted))]">{filename}</p>
      <div className="space-y-3">
        {STAGES.map((s, i) => {
          const idx = STAGES.findIndex((x) => x.key === stage);
          const isActive = s.key === stage;
          const isDone = i < idx;
          return (
            <div key={s.key} className="flex items-center gap-3 text-sm">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center">
                {isDone ? <CheckCircle2 className="h-5 w-5 text-gain" />
                  : isActive ? <Loader2 className="h-5 w-5 animate-spin text-accent" />
                  : <span className="h-2 w-2 rounded-full bg-[hsl(var(--border))]" />}
              </span>
              <span className={cn(
                isActive ? "text-[hsl(var(--text))]" : isDone ? "text-gain" : "text-[hsl(var(--text-muted))]",
              )}>{s.label}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-6 text-center text-[11px] text-[hsl(var(--text-muted))]">Usually 5–15 seconds.</p>
    </div>
  );
}

function ReviewStep({
  extraction,
  selectedTxs, toggleTx,
  selectedHoldings, toggleHolding,
  acceptName, setAcceptName,
  acceptIncome, setAcceptIncome,
  accounts, accountId, setAccountId,
  onPickAnother,
}: {
  extraction: ProfileExtraction;
  selectedTxs: Set<number>;
  toggleTx: (i: number) => void;
  selectedHoldings: Set<number>;
  toggleHolding: (i: number) => void;
  acceptName: boolean;
  setAcceptName: (v: boolean) => void;
  acceptIncome: boolean;
  setAcceptIncome: (v: boolean) => void;
  accounts: Account[];
  accountId: number | null;
  setAccountId: (id: number | null) => void;
  onPickAnother: () => void;
}) {
  if (extraction.needs_better_document) {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
          <div>
            <p className="text-sm font-medium">This document isn't quite right</p>
            <p className="mt-1 text-xs">{extraction.needs_better_document}</p>
          </div>
        </div>
        <p className="text-xs text-[hsl(var(--text-muted))]">{extraction.summary}</p>
        <Button variant="secondary" onClick={onPickAnother} className="w-full">
          Try a different file
        </Button>
      </div>
    );
  }

  const txs = extraction.suggested_transactions;
  const holdings = extraction.suggested_holdings;
  const conf = Math.round(extraction.doc_type_confidence * 100);

  return (
    <div className="space-y-5">
      {/* Summary */}
      <div className="flex items-start gap-3 rounded-lg bg-accent-muted/40 p-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {DOC_TYPE_LABELS[extraction.doc_type]}
            <span className="ml-2 text-xs text-[hsl(var(--text-muted))]">{conf}% confident</span>
          </p>
          <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">{extraction.summary}</p>
        </div>
      </div>

      {/* Account selector — applies to all transactions */}
      {txs.length > 0 && accounts.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] p-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[hsl(var(--text-muted))]">
              Add transactions to which account?
            </span>
            <Select
              options={[
                { value: "", label: "— don't link to an account —" },
                ...accounts.map((a) => ({ value: String(a.id), label: `${a.name} (${a.currency})` })),
              ]}
              value={accountId == null ? "" : String(accountId)}
              onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
            />
          </label>
          <p className="mt-1 text-[10px] text-[hsl(var(--text-muted))]">
            Linking updates the account balance automatically.
          </p>
        </div>
      )}

      {/* Transactions */}
      {txs.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))]">
            Transactions ({txs.length})
          </h3>
          <ul className="space-y-1.5">
            {txs.map((t, i) => (
              <TxRow key={i} tx={t} checked={selectedTxs.has(i)} onToggle={() => toggleTx(i)} />
            ))}
          </ul>
        </section>
      )}

      {/* Holdings — secondary, with explanation */}
      {holdings.length > 0 && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            <TrendingUp className="h-3.5 w-3.5 text-accent" />
            <h3 className="text-xs font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Investments → goes to Portfolio ({holdings.length})
            </h3>
          </div>
          <p className="mb-2 text-[11px] text-[hsl(var(--text-muted))]">
            These look like investment positions. Selected ones are added to your Portfolio.
          </p>
          <ul className="space-y-1.5">
            {holdings.map((h, i) => (
              <HoldingRow key={i} holding={h}
                checked={selectedHoldings.has(i)} onToggle={() => toggleHolding(i)} />
            ))}
          </ul>
        </section>
      )}

      {/* Profile */}
      {extraction.suggested_profile && (
        (extraction.suggested_profile.name || extraction.suggested_profile.monthly_income != null) && (
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Profile
            </h3>
            <div className="space-y-1.5">
              {extraction.suggested_profile.name && (
                <CheckRow checked={acceptName} onToggle={() => setAcceptName(!acceptName)}
                  label="Set name" value={extraction.suggested_profile.name} />
              )}
              {extraction.suggested_profile.monthly_income != null && (
                <CheckRow checked={acceptIncome} onToggle={() => setAcceptIncome(!acceptIncome)}
                  label="Set monthly income"
                  value={`${extraction.suggested_profile.monthly_income.toLocaleString()} ${extraction.suggested_profile.currency ?? ""}`} />
              )}
            </div>
          </section>
        )
      )}

      {txs.length === 0 && holdings.length === 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4 text-center text-xs text-[hsl(var(--text-muted))]">
          No financial rows found in this document, but it was readable.
        </div>
      )}

      {extraction.missing_or_unclear.length > 0 && (
        <details className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs">
          <summary className="cursor-pointer font-medium text-warning">
            {extraction.missing_or_unclear.length} field{extraction.missing_or_unclear.length === 1 ? "" : "s"} need a closer look
          </summary>
          <ul className="mt-2 space-y-1 pl-4 text-[hsl(var(--text-muted))] list-disc">
            {extraction.missing_or_unclear.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function TxRow({
  tx, checked, onToggle,
}: {
  tx: TransactionSuggestion;
  checked: boolean;
  onToggle: () => void;
}) {
  const incomplete = !isCompleteTx(tx);
  const isIncome = (tx.amount ?? 0) > 0 && tx.type === "income";
  const amount = tx.amount != null
    ? `${isIncome ? "+" : "−"}${Math.abs(tx.amount).toLocaleString()} ${tx.currency ?? ""}`
    : "—";

  return (
    <li
      onClick={onToggle}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition",
        checked ? "border-accent bg-accent-muted/40"
          : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
        incomplete && "opacity-60 cursor-not-allowed",
      )}
    >
      <span className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
        checked ? "border-accent bg-accent" : "border-[hsl(var(--border))]",
      )}>
        {checked && <CheckCircle2 className="h-3 w-3 text-white" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm">{tx.description || "(no description)"}</span>
          {tx.category && (
            <span className="shrink-0 rounded bg-[hsl(var(--surface))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))]">
              {tx.category}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[10px] text-[hsl(var(--text-muted))]">
          {tx.occurred_on ?? "no date"} · {tx.type ?? "unknown"}
        </p>
      </div>
      <span className={cn(
        "shrink-0 font-mono text-sm tabular-nums",
        isIncome ? "text-gain" : "text-[hsl(var(--text))]",
      )}>
        {amount}
      </span>
    </li>
  );
}

function HoldingRow({
  holding, checked, onToggle,
}: {
  holding: HoldingSuggestion;
  checked: boolean;
  onToggle: () => void;
}) {
  const incomplete = holding.quantity == null || holding.quantity <= 0;
  return (
    <li
      onClick={onToggle}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition",
        checked ? "border-accent bg-accent-muted/40"
          : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
        incomplete && "opacity-60",
      )}
    >
      <span className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
        checked ? "border-accent bg-accent" : "border-[hsl(var(--border))]",
      )}>
        {checked && <CheckCircle2 className="h-3 w-3 text-white" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">{holding.ticker}</span>
          <span className="rounded bg-[hsl(var(--surface))] px-1.5 py-0.5 text-[10px] uppercase text-[hsl(var(--text-muted))]">
            {holding.asset_class}
          </span>
        </div>
        <p className="mt-0.5 text-[10px] text-[hsl(var(--text-muted))]">
          {holding.quantity != null ? `${holding.quantity} units` : "quantity unknown"}
          {holding.cost_basis != null && ` · @ ${holding.cost_basis} ${holding.currency ?? ""}`}
        </p>
      </div>
    </li>
  );
}

function CheckRow({
  checked, onToggle, label, value,
}: { checked: boolean; onToggle: () => void; label: string; value: string }) {
  return (
    <div
      onClick={onToggle}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition",
        checked ? "border-accent bg-accent-muted/40"
          : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
      )}
    >
      <span className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
        checked ? "border-accent bg-accent" : "border-[hsl(var(--border))]",
      )}>
        {checked && <CheckCircle2 className="h-3 w-3 text-white" />}
      </span>
      <div className="min-w-0 flex-1 text-sm">
        <span className="text-[hsl(var(--text-muted))]">{label}: </span>
        <span className="font-medium">{value}</span>
      </div>
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
