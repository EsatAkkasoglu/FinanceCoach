/**
 * Documents — stateless drop-zone for AI document parsing.
 *
 * The backend (/documents/parse) is stateless; nothing is persisted. This page
 * surfaces what BudgetImportModal already does, plus the parts BudgetImport
 * ignores: the AI's follow_up_questions, missing_or_unclear warnings, and
 * any risk_signals — so the user sees why the parse confidence is what it is
 * and can hand questions off to the Coach.
 */
import { useRef, useState, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Upload, FileText, AlertTriangle, Sparkles, Loader2, MessageSquare,
  Shield, X, Trash2, Clock,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  parseDocument, listDocuments, deleteDocument,
  type ProfileExtraction, type DocumentEntry,
} from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { buildLocalizedPath, getLanguageFromPath } from "@/lib/routing";

const ACCEPTED = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.csv";
const MAX_BYTES = 50 * 1024 * 1024;

interface ParsedDoc {
  filename: string;
  size: number;
  result: ProfileExtraction;
}

export function Documents() {
  const { t } = useTranslation("documents");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [parsing, setParsing] = useState(false);
  // Session-scoped parse results (richer: extraction result + size).
  const [parsed, setParsed] = useState<ParsedDoc[]>([]);
  // Persistent document list from ChromaDB.
  const [savedDocs, setSavedDocs] = useState<DocumentEntry[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();
  const lang = getLanguageFromPath(location.pathname) ?? "en";

  const refreshList = useCallback(async () => {
    try {
      const docs = await listDocuments();
      setSavedDocs(docs);
    } catch {
      // silently ignore — list is best-effort
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => { void refreshList(); }, [refreshList]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const f = files[0];
    if (f.size > MAX_BYTES) {
      toast.error(t("fileTooLarge"));
      return;
    }
    setParsing(true);
    try {
      const result = await parseDocument(f);
      setParsed((prev) => [{ filename: f.name, size: f.size, result }, ...prev]);
      // Refresh persistent list so the new file appears immediately.
      void refreshList();
    } catch (e) {
      toast.error((e as Error).message || t("parseFailed"));
    } finally {
      setParsing(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleDelete(filename: string) {
    try {
      await deleteDocument(filename);
      setSavedDocs((prev) => prev.filter((d) => d.filename !== filename));
      toast.success(`"${filename}" silindi`);
    } catch {
      toast.error("Belge silinemedi");
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    void handleFiles(e.dataTransfer.files);
  }

  async function askCoach(question: string) {
    try {
      await navigator.clipboard.writeText(question);
      toast.success(t("questionCopied"));
    } catch {
      // ignore — clipboard may be unavailable in some webviews
    }
    navigate(buildLocalizedPath(lang, `/chat`));
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-sm text-content-muted">
            {t("subtitle")}
          </p>
        </div>
      </header>

      {/* Drop zone */}
      <label
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "card flex cursor-pointer flex-col items-center justify-center gap-3 py-14 text-center transition",
          dragging && "border-accent bg-accent/5",
          parsing && "pointer-events-none opacity-60",
        )}
      >
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent shadow-glow">
          {parsing ? <Loader2 className="h-6 w-6 animate-spin" /> : <Upload className="h-6 w-6" />}
        </div>
        <div>
          <p className="text-sm font-semibold">
            {parsing ? t("parsing") : t("dropPrompt")}
          </p>
          <p className="mt-1 text-xs text-content-muted">
            {t("fileHint")}
          </p>
        </div>
      </label>

      {/* Session results — richer extraction view */}
      {parsed.length > 0 && (
        <section className="space-y-4">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
            {t("thisSession")}
          </p>
          {parsed.map((doc, idx) => (
            <ParsedDocCard
              key={`${doc.filename}-${idx}`}
              doc={doc}
              onAskCoach={askCoach}
              onDismiss={() => setParsed((prev) => prev.filter((_, i) => i !== idx))}
            />
          ))}
        </section>
      )}

      {/* Persistent document library — always shown */}
      <section className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
          Yüklenen Belgeler
        </p>

        {loadingList ? (
          <div className="flex items-center gap-2 text-sm text-content-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            Yükleniyor…
          </div>
        ) : savedDocs.length === 0 ? (
          <p className="text-sm text-content-muted">
            Henüz belge yüklenmemiş. Yukarıdan bir dosya bırakın.
          </p>
        ) : (
          <ul className="space-y-2">
            {savedDocs.map((doc) => (
              <li
                key={doc.filename}
                className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-raised px-4 py-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-content-muted">
                    <FileText className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{doc.filename}</p>
                    <p className="flex items-center gap-1 mt-0.5 text-xs text-content-muted">
                      <Clock className="h-3 w-3" />
                      {doc.created_at_iso
                        ? new Date(doc.created_at_iso).toLocaleString("tr-TR", {
                            day: "2-digit", month: "short", year: "numeric",
                            hour: "2-digit", minute: "2-digit",
                          })
                        : "—"}
                      <span className="ml-1 rounded-full bg-surface px-1.5 py-0.5 text-[10px]">
                        {doc.chunk_count} parça
                      </span>
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(doc.filename)}
                  className="rounded-lg p-2 text-content-muted transition hover:bg-surface hover:text-red-400"
                  title="Sil"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="pt-2 text-[10px] text-content-muted">
        {t("disclaimer")}
      </p>
    </div>
  );
}

function ParsedDocCard({
  doc,
  onAskCoach,
  onDismiss,
}: {
  doc: ParsedDoc;
  onAskCoach: (q: string) => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation("documents");
  const r = doc.result;
  const confidencePct = Math.round(r.doc_type_confidence * 100);
  const sizeKb = (doc.size / 1024).toFixed(0);
  const docTypeLabel = t(`docTypes.${r.doc_type}`, { defaultValue: t("docTypes.other") });

  return (
    <article className="card space-y-4">
      {/* Header */}
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-raised text-content-muted">
            <FileText className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-semibold">{doc.filename}</h2>
              <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] font-medium text-content-muted">
                {docTypeLabel} · {confidencePct}%
              </span>
            </div>
            <p className="mt-0.5 text-xs text-content-muted">{sizeKb} KB</p>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="rounded p-1.5 text-content-muted transition hover:bg-surface-raised hover:text-content"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </header>

      {/* Summary */}
      <p className="rounded-lg bg-surface-raised px-3 py-2.5 text-sm text-content">
        {r.summary}
      </p>

      {/* If document is unusable */}
      {r.needs_better_document && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2.5 text-xs text-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{r.needs_better_document}</span>
        </div>
      )}

      {/* Extracted counts */}
      <div className="grid grid-cols-3 gap-3">
        <Stat label={t("holdings")} value={r.suggested_holdings.length} />
        <Stat label={t("transactions")} value={r.suggested_transactions.length} />
        <Stat
          label={t("profileHints")}
          value={r.suggested_profile?.monthly_income ? 1 : 0}
        />
      </div>

      {/* Follow-up questions — the headline feature of this page */}
      {r.follow_up_questions.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
            <Sparkles className="h-3.5 w-3.5 text-accent" />
            {t("coachWantsToKnow")}
          </p>
          <ul className="space-y-2">
            {r.follow_up_questions.map((q, i) => (
              <li
                key={i}
                className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-raised px-3 py-2.5"
              >
                <span className="text-sm">{q}</span>
                <Button size="sm" variant="ghost" onClick={() => onAskCoach(q)}>
                  <MessageSquare className="h-3.5 w-3.5" />
                  {t("askCoach")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Risk signals */}
      {r.suggested_profile?.risk_signals && r.suggested_profile.risk_signals.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
            <Shield className="h-3.5 w-3.5 text-accent" />
            {t("riskSignals")}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {r.suggested_profile.risk_signals.map((s, i) => (
              <span
                key={i}
                className="rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-[11px] text-accent"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Missing or unclear */}
      {r.missing_or_unclear.length > 0 && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" />
            {t("unclear")}
          </p>
          <ul className="space-y-1 text-xs text-content-muted">
            {r.missing_or_unclear.map((m, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning" />
                <span>{m}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card-muted">
      <p className="text-overline uppercase text-content-muted">
        {label}
      </p>
      <p className="mt-1 font-mono text-lg font-semibold tabular-nums">
        {value === 0 ? "—" : value}
      </p>
    </div>
  );
}
