import { useEffect, useRef, useState } from "react";
import {
  Upload, FileText, X, AlertTriangle, CheckCircle2, Sparkles, Loader2,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import {
  parseDocument, addHolding, updateProfile,
  type ProfileExtraction, type HoldingSuggestion,
} from "@/lib/api";
import { cn } from "@/lib/cn";

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
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

export function ImportDocumentModal({ open, onClose, onImported }: Props) {
  const [step, setStep] = useState<Step>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<Stage>("uploading");
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ProfileExtraction | null>(null);

  // Selection state for the review screen
  const [selectedHoldings, setSelectedHoldings] = useState<Set<number>>(new Set());
  const [acceptName, setAcceptName] = useState(true);
  const [acceptIncome, setAcceptIncome] = useState(true);
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
    setSelectedHoldings(new Set());
    setAcceptName(true);
    setAcceptIncome(true);
    setImporting(false);
    if (abortRef.current) abortRef.current.abort();
    if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
  }

  useEffect(() => {
    if (!open) reset();
    return () => {
      if (abortRef.current) abortRef.current.abort();
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

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  }

  async function startParsing() {
    if (!file) return;
    setStep("loading");
    setStage("uploading");
    setError(null);

    // Visual progression — purely cosmetic; the request is one round-trip.
    if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
    stageTimerRef.current = window.setTimeout(() => setStage("analyzing"), 700);
    const t2 = window.setTimeout(() => setStage("preparing"), 4500);

    abortRef.current = new AbortController();
    try {
      const result = await parseDocument(file, abortRef.current.signal);
      window.clearTimeout(t2);
      if (stageTimerRef.current) window.clearTimeout(stageTimerRef.current);
      setExtraction(result);
      setSelectedHoldings(new Set(result.suggested_holdings.map((_, i) => i)));
      setStep("review");
    } catch (err) {
      window.clearTimeout(t2);
      if ((err as Error).name === "AbortError") return;
      setError((err as Error).message || "Failed to read document");
      setStep("pick");
    }
  }

  function toggleHolding(idx: number) {
    setSelectedHoldings((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  async function handleImport() {
    if (!extraction) return;
    setImporting(true);
    let added = 0;
    let failed = 0;

    const toImport = Array.from(selectedHoldings).map((i) => extraction.suggested_holdings[i]);
    for (const h of toImport) {
      if (!h || !h.quantity || h.quantity <= 0) { failed++; continue; }
      try {
        await addHolding({
          ticker: h.ticker,
          quantity: h.quantity,
          cost_basis: h.cost_basis ?? 0,
          asset_class: h.asset_class,
        });
        added++;
      } catch {
        failed++;
      }
    }

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
    if (added > 0) toast.success(`${added} holding${added === 1 ? "" : "s"} imported`);
    if (failed > 0) toast.warning(`${failed} suggestion${failed === 1 ? "" : "s"} skipped (missing data)`);
    if (added === 0 && failed === 0) toast.success("Profile updated");
    onImported();
    onClose();
  }

  // ── Render ─────────────────────────────────────────────────────────────

  const title = step === "review" ? "Review what we found" : "Import from document";
  const description = step === "review"
    ? "Pick what to add. You can edit anything afterwards."
    : "Drop a PDF, screenshot, or document. The AI extracts holdings and profile info — nothing is saved without your confirmation.";

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
        <PickStep
          file={file}
          error={error}
          onPick={pickFile}
          onDrop={onDrop}
          onClear={() => setFile(null)}
          fileInputRef={fileInputRef}
        />
      )}
      {step === "loading" && <LoadingStep stage={stage} filename={file?.name ?? ""} />}
      {step === "review" && extraction && (
        <ReviewStep
          extraction={extraction}
          selected={selectedHoldings}
          onToggle={toggleHolding}
          acceptName={acceptName}
          setAcceptName={setAcceptName}
          acceptIncome={acceptIncome}
          setAcceptIncome={setAcceptIncome}
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
    // review
    const totalSelected = selectedHoldings.size
      + (acceptName && extraction?.suggested_profile?.name ? 1 : 0)
      + (acceptIncome && extraction?.suggested_profile?.monthly_income != null ? 1 : 0);
    return (
      <>
        <Button variant="ghost" onClick={() => reset()}>Pick another file</Button>
        <Button onClick={handleImport} loading={importing} disabled={totalSelected === 0}>
          {totalSelected === 0 ? "Nothing selected" : `Import ${totalSelected} item${totalSelected === 1 ? "" : "s"}`}
        </Button>
      </>
    );
  }
}

// ── Step components ─────────────────────────────────────────────────────────

function PickStep({
  file, error, onPick, onDrop, onClear, fileInputRef,
}: {
  file: File | null;
  error: string | null;
  onPick: (f: File) => void;
  onDrop: (e: React.DragEvent) => void;
  onClear: () => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
}) {
  const [dragOver, setDragOver] = useState(false);

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { setDragOver(false); onDrop(e); }}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-8 py-12 text-center transition",
          dragOver
            ? "border-accent bg-accent/5"
            : "border-line hover:border-content-muted hover:bg-surface-raised",
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-muted">
          <Upload className="h-5 w-5 text-accent" />
        </div>
        <p className="text-sm font-medium">Drop a file here, or click to browse</p>
        <p className="text-xs text-content-muted">PDF, image, docx, csv — up to 50 MB</p>
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
        <div className="flex items-center gap-3 rounded-lg border border-line bg-surface-raised px-3 py-2.5">
          <FileText className="h-4 w-4 shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-content-muted">{formatBytes(file.size)}</p>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onClear(); }}
            className="rounded p-1 text-content-muted hover:bg-surface hover:text-loss"
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

      <p className="rounded-lg bg-surface-raised/60 px-3 py-2 text-[11px] text-content-muted">
        🔒 Files are sent to Gemini for analysis only. We don't store them.
      </p>
    </div>
  );
}

function LoadingStep({ stage, filename }: { stage: Stage; filename: string }) {
  return (
    <div className="py-8">
      <p className="mb-6 truncate text-center text-xs text-content-muted">{filename}</p>
      <div className="space-y-3">
        {STAGES.map((s, i) => {
          const currentIdx = STAGES.findIndex((x) => x.key === stage);
          const isActive = s.key === stage;
          const isDone = i < currentIdx;
          return (
            <div key={s.key} className="flex items-center gap-3 text-sm">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center">
                {isDone ? (
                  <CheckCircle2 className="h-5 w-5 text-gain" />
                ) : isActive ? (
                  <Loader2 className="h-5 w-5 animate-spin text-accent" />
                ) : (
                  <span className="h-2 w-2 rounded-full bg-default" />
                )}
              </span>
              <span className={cn(
                isActive ? "text-content" : isDone ? "text-gain" : "text-content-muted",
              )}>
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-6 text-center text-[11px] text-content-muted">
        Usually takes 5–15 seconds.
      </p>
    </div>
  );
}

function ReviewStep({
  extraction, selected, onToggle,
  acceptName, setAcceptName,
  acceptIncome, setAcceptIncome,
  onPickAnother,
}: {
  extraction: ProfileExtraction;
  selected: Set<number>;
  onToggle: (i: number) => void;
  acceptName: boolean;
  setAcceptName: (v: boolean) => void;
  acceptIncome: boolean;
  setAcceptIncome: (v: boolean) => void;
  onPickAnother: () => void;
}) {
  const docLabel = DOC_TYPE_LABELS[extraction.doc_type];
  const conf = Math.round(extraction.doc_type_confidence * 100);

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
        <p className="text-xs text-content-muted">{extraction.summary}</p>
        <Button variant="secondary" onClick={onPickAnother} className="w-full">
          Try a different file
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Doc summary */}
      <div className="flex items-start gap-3 rounded-lg bg-accent-muted/40 p-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {docLabel} <span className="ml-2 text-xs text-content-muted">{conf}% confident</span>
          </p>
          <p className="mt-0.5 text-xs text-content-muted">{extraction.summary}</p>
        </div>
      </div>

      {/* Holdings */}
      {extraction.suggested_holdings.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
            Holdings ({extraction.suggested_holdings.length})
          </h3>
          <ul className="space-y-1.5">
            {extraction.suggested_holdings.map((h, i) => (
              <HoldingRow
                key={i}
                holding={h}
                checked={selected.has(i)}
                onToggle={() => onToggle(i)}
              />
            ))}
          </ul>
        </section>
      )}

      {/* Profile suggestions */}
      {extraction.suggested_profile && (
        (extraction.suggested_profile.name || extraction.suggested_profile.monthly_income != null) && (
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
              Profile
            </h3>
            <div className="space-y-1.5">
              {extraction.suggested_profile.name && (
                <CheckRow
                  checked={acceptName}
                  onToggle={() => setAcceptName(!acceptName)}
                  label="Set name"
                  value={extraction.suggested_profile.name}
                />
              )}
              {extraction.suggested_profile.monthly_income != null && (
                <CheckRow
                  checked={acceptIncome}
                  onToggle={() => setAcceptIncome(!acceptIncome)}
                  label="Set monthly income"
                  value={`${extraction.suggested_profile.monthly_income.toLocaleString()} ${extraction.suggested_profile.currency ?? ""}`}
                />
              )}
            </div>
          </section>
        )
      )}

      {/* Empty case */}
      {extraction.suggested_holdings.length === 0
        && (!extraction.suggested_profile
          || (!extraction.suggested_profile.name && extraction.suggested_profile.monthly_income == null)) && (
        <div className="rounded-lg border border-line bg-surface-raised p-4 text-center text-xs text-content-muted">
          No portfolio data found in this document, but it was readable.
        </div>
      )}

      {/* Warnings */}
      {extraction.missing_or_unclear.length > 0 && (
        <details className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs">
          <summary className="cursor-pointer font-medium text-warning">
            {extraction.missing_or_unclear.length} field{extraction.missing_or_unclear.length === 1 ? "" : "s"} need a closer look
          </summary>
          <ul className="mt-2 space-y-1 pl-4 text-content-muted list-disc">
            {extraction.missing_or_unclear.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        </details>
      )}

      {/* Follow-ups */}
      {extraction.follow_up_questions.length > 0 && (
        <div className="rounded-lg border border-line bg-surface-raised p-3">
          <p className="mb-2 text-xs font-medium">The assistant suggests asking:</p>
          <ul className="space-y-1.5 text-xs text-content-muted">
            {extraction.follow_up_questions.map((q, i) => <li key={i}>• {q}</li>)}
          </ul>
        </div>
      )}
    </div>
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
  const lowConf = holding.confidence < 0.7;

  return (
    <li
      onClick={onToggle}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition",
        checked
          ? "border-accent bg-accent-muted/40"
          : "border-line bg-surface-raised hover:border-content-muted",
        incomplete && "opacity-60",
      )}
    >
      <span className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
        checked ? "border-accent bg-accent" : "border-line",
      )}>
        {checked && <CheckCircle2 className="h-3 w-3 text-white" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">{holding.ticker}</span>
          <span className="rounded bg-surface px-1.5 py-0.5 text-overline uppercase text-content-muted">
            {holding.asset_class}
          </span>
          {lowConf && !incomplete && (
            <span className="text-[10px] text-warning">low confidence</span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-content-muted">
          {holding.quantity != null ? `${holding.quantity} units` : "quantity unknown"}
          {holding.cost_basis != null && ` · @ ${holding.cost_basis} ${holding.currency ?? ""}`}
        </p>
      </div>
      {incomplete && (
        <span className="shrink-0 text-[10px] text-warning">needs review</span>
      )}
    </li>
  );
}

function CheckRow({
  checked, onToggle, label, value,
}: {
  checked: boolean;
  onToggle: () => void;
  label: string;
  value: string;
}) {
  return (
    <div
      onClick={onToggle}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition",
        checked
          ? "border-accent bg-accent-muted/40"
          : "border-line bg-surface-raised hover:border-content-muted",
      )}
    >
      <span className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded border-2",
        checked ? "border-accent bg-accent" : "border-line",
      )}>
        {checked && <CheckCircle2 className="h-3 w-3 text-white" />}
      </span>
      <div className="min-w-0 flex-1 text-sm">
        <span className="text-content-muted">{label}: </span>
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
