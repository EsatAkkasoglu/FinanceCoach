import { useEffect, useRef, useState } from "react";
import { Send, Square, Trash2, Copy, Check, Loader2, ThumbsUp, ThumbsDown, RotateCcw, Paperclip, X, FileText, FileSpreadsheet, FileCode, Image as ImageIcon, File as FileIcon, AlertCircle, UploadCloud, Mic, Sparkles } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { streamChat, sendFeedback, autotitleConversation, parseDocument, transcribeAudio, type Citation as ApiCitation } from "@/lib/api";
import { useChatStore, useAgentVizStore, useConversationStore, useSettingsStore, type ToolActivity, type MessageAttachment } from "@/store";
import { cn } from "@/lib/cn";
import { AgentBadge } from "./AgentBadge";
import { AgentTrace } from "./AgentTrace";
import { Disclaimer } from "@/components/ui/Disclaimer";

function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, n);
}

interface ChatPanelProps {
  convId: string;
  threadId: string;
}

// ── Attachments ──────────────────────────────────────────────────────────────
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
const MAX_FILES = 6;
const MAX_TEXT_CHARS = 8000;
const TEXT_EXT_RE = /\.(txt|md|markdown|csv|tsv|json|ya?ml|log|html?|xml|js|jsx|ts|tsx|py|rb|go|rs|java|kt|swift|c|cpp|h|hpp|cs|css|scss|sass|sh|bash|zsh|sql|env|toml|ini|conf)$/i;
const PDF_RE = /\.pdf$/i;
const SPREAD_RE = /\.(xlsx?|xlsm|ods)$/i;

type AttachmentKind = "text" | "image" | "pdf" | "spreadsheet" | "other";
type AttachmentStatus = "uploading" | "ready" | "error";

interface Attachment {
  id: string;
  name: string;
  size: number;
  mime: string;
  kind: AttachmentKind;
  status: AttachmentStatus;
  progress: number;
  summary?: string;
  excerpt?: string;
  error?: string;
}

// In-memory cache of the actual File objects so chips can re-open them after send.
// Survives the session but not a page reload — that's intentional (no 5MB blobs in localStorage).
const fileRefCache = new Map<string, File>();

function openAttachment(att: MessageAttachment) {
  const file = fileRefCache.get(att.id);
  if (!file) {
    toast.info(`"${att.name}" bu oturumda artık açılamaz (sayfa yenilendi).`);
    return;
  }
  const url = URL.createObjectURL(file);
  const previewable = att.kind === "image" || att.kind === "pdf" || att.kind === "text" || att.kind === "code";
  if (previewable) {
    window.open(url, "_blank", "noopener,noreferrer");
    // Revoke after a delay so the new tab has time to load.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } else {
    const a = document.createElement("a");
    a.href = url;
    a.download = att.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 5_000);
  }
}

function MessageAttachments({ attachments }: { attachments: MessageAttachment[] }) {
  return (
    <div className="not-prose mb-2 flex flex-wrap gap-2">
      {attachments.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => openAttachment(a)}
          title={`${a.name} · ${humanSize(a.size)}`}
          className={cn(
            "group/att flex items-center gap-2 rounded-lg border border-line",
            "bg-surface-raised/70 px-2.5 py-1.5 text-left",
            "transition-all duration-200 ease-out",
            "hover:-translate-y-0.5 hover:border-accent/60 hover:bg-surface-raised hover:shadow-[0_0_0_1px_hsl(var(--accent)/0.25),0_4px_16px_-4px_hsl(var(--accent)/0.35)]",
            "active:translate-y-0 active:scale-[0.98]"
          )}
        >
          <span className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
            "bg-accent/10 text-accent transition-transform duration-200",
            "group-hover/att:scale-110 group-hover/att:bg-accent/20"
          )}>
            <KindIcon kind={a.kind === "binary" ? "other" : (a.kind as AttachmentKind)} className="h-4 w-4" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate max-w-[200px] text-xs font-medium text-content">
              {a.name}
            </span>
            <span className="text-overline uppercase text-content-muted">
              {a.kind} · {humanSize(a.size)}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

function detectKind(file: File): AttachmentKind {
  if (file.type.startsWith("image/")) return "image";
  if (PDF_RE.test(file.name) || file.type === "application/pdf") return "pdf";
  if (SPREAD_RE.test(file.name)) return "spreadsheet";
  if (TEXT_EXT_RE.test(file.name) || file.type.startsWith("text/") || file.type === "application/json") return "text";
  return "other";
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function KindIcon({ kind, className }: { kind: AttachmentKind; className?: string }) {
  const cls = cn("h-3.5 w-3.5", className);
  switch (kind) {
    case "image": return <ImageIcon className={cls} />;
    case "pdf": return <FileText className={cls} />;
    case "spreadsheet": return <FileSpreadsheet className={cls} />;
    case "text": return <FileCode className={cls} />;
    default: return <FileIcon className={cls} />;
  }
}

function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("read error"));
    reader.readAsText(file);
  });
}

export function ChatPanel({ convId, threadId }: ChatPanelProps) {
  const { t, i18n } = useTranslation("chat");
  const {
    messagesByConv, streaming,
    appendMessage, appendToken, setMessageAgent, addCitations, setMessageSteps, setMessageSuggestions, addReasoning, setStreaming, resetConv,
  } = useChatStore();
  const messages = messagesByConv[convId] ?? [];
  const clearAgentEvents = useAgentVizStore((s) => s.clear);
  const updateTitle = useConversationStore((s) => s.updateTitle);
  const activeConv = useConversationStore((s) => s.conversations.find((c) => c.id === convId));
  const displayCurrency = useSettingsStore((s) => s.displayCurrency);
  const [input, setInput] = useState("");
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [suggestions] = useState<string[]>(() => {
    const raw = t("suggestionPool", { returnObjects: true });
    return pickRandom(Array.isArray(raw) ? (raw as string[]) : [], 4);
  });
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const toolActivitiesRef = useRef<ToolActivity[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [stoppedPrompt, setStoppedPrompt] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const inFlightPromptRef = useRef<string | null>(null);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastAsstId = useRef<string | null>(null);
  // Tracks which agents have already been assigned a bubble this turn.
  // On agent_start for a non-supervisor agent: if the current bubble already
  // has content, a new bubble is created so each agent response is distinct.
  const seenAgentsThisTurn = useRef<Set<string>>(new Set());
  // run_id → {tool, args, result} captured during streaming so we can attach
  // tool results to citations when the citations event arrives at the end.
  const toolRunsRef = useRef<Map<string, { tool: string; argsKey: string; result?: string }>>(new Map());

  // Auto-scroll on new messages or while tokens stream in.
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Deep-link seed: a "?ask=…" param (e.g. from a news-alert "ask the coach"
  // CTA) pre-fills the composer once, then is cleared so a refresh / back nav
  // doesn't re-seed. The user still presses send — we never auto-submit.
  const [searchParams, setSearchParams] = useSearchParams();
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    const ask = searchParams.get("ask");
    if (!ask) return;
    seededRef.current = true;
    setInput((prev) => (prev ? prev : ask));
    const next = new URLSearchParams(searchParams);
    next.delete("ask");
    setSearchParams(next, { replace: true });
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [searchParams, setSearchParams]);

  // Auto-resize textarea up to 6 lines.
  function autoResize() {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 168)}px`;
  }
  useEffect(autoResize, [input]);

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
  }

  function updateAttachment(id: string, patch: Partial<Attachment>) {
    setAttachments((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  async function processAttachment(att: Attachment, file: File) {
    // Indeterminate progress ramp until analysis resolves.
    let pct = 8;
    const tick = window.setInterval(() => {
      pct = Math.min(90, pct + Math.max(2, Math.round((90 - pct) * 0.12)));
      updateAttachment(att.id, { progress: pct });
    }, 220);
    try {
      let summary: string | undefined;
      let excerpt: string | undefined;
      if (att.kind === "text") {
        const raw = await readAsText(file);
        excerpt = raw.length > MAX_TEXT_CHARS ? raw.slice(0, MAX_TEXT_CHARS) + "\n…(truncated)" : raw;
        const lines = raw.split(/\r?\n/).length;
        summary = t("attach.summaryText", { lines, chars: raw.length });
      } else if (att.kind === "pdf" || att.kind === "image") {
        try {
          const res = await parseDocument(file);
          const parts: string[] = [];
          if (res.summary) parts.push(res.summary);
          if (res.suggested_holdings?.length) {
            parts.push(t("attach.holdingsFound", { count: res.suggested_holdings.length }));
          }
          if (res.suggested_transactions?.length) {
            parts.push(t("attach.txFound", { count: res.suggested_transactions.length }));
          }
          summary = parts.join(" · ") || t("attach.summaryGeneric", { kind: att.kind });
          if (res.extracted_text) {
            const MAX_CHARS = 12000;
            excerpt = res.extracted_text.length > MAX_CHARS
              ? res.extracted_text.slice(0, MAX_CHARS) + "\n…(truncated)"
              : res.extracted_text;
          }
        } catch {
          summary = t("attach.summaryGeneric", { kind: att.kind });
        }
      } else {
        summary = t("attach.summaryBinary");
      }
      window.clearInterval(tick);
      updateAttachment(att.id, { status: "ready", progress: 100, summary, excerpt });
    } catch (err) {
      window.clearInterval(tick);
      updateAttachment(att.id, {
        status: "error",
        progress: 0,
        error: (err as Error).message || String(err),
      });
    }
  }

  function addFiles(list: FileList | File[]) {
    const files = Array.from(list);
    if (files.length === 0) return;
    const currentCount = attachments.length;
    const room = MAX_FILES - currentCount;
    if (room <= 0) {
      toast.error(t("attach.maxReached", { max: MAX_FILES }));
      return;
    }
    const accepted: { att: Attachment; file: File }[] = [];
    for (const file of files.slice(0, room)) {
      if (file.size > MAX_FILE_SIZE) {
        toast.error(t("attach.tooLarge", { name: file.name, max: humanSize(MAX_FILE_SIZE) }));
        continue;
      }
      const att: Attachment = {
        id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: file.name,
        size: file.size,
        mime: file.type || "application/octet-stream",
        kind: detectKind(file),
        status: "uploading",
        progress: 4,
      };
      accepted.push({ att, file });
      fileRefCache.set(att.id, file);
    }
    if (accepted.length === 0) return;
    setAttachments((prev) => [...prev, ...accepted.map((a) => a.att)]);
    accepted.forEach(({ att, file }) => void processAttachment(att, file));
    if (files.length > room) {
      toast.warning(t("attach.someSkipped", { skipped: files.length - room }));
    }
  }

  function retryAttachment(id: string) {
    // Re-open picker for that slot — simpler than holding the File reference.
    removeAttachment(id);
    fileInputRef.current?.click();
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) addFiles(e.target.files);
    e.target.value = ""; // allow re-picking the same file
  }

  function onDragEnter(e: React.DragEvent) {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
    dragCounter.current += 1;
    setIsDragging(true);
  }
  function onDragOver(e: React.DragEvent) {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
  }
  function onDragLeave(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current = Math.max(0, dragCounter.current - 1);
    if (dragCounter.current === 0) setIsDragging(false);
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragging(false);
    if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
  }

  function buildAgentContextFromMeta(atts: MessageAttachment[]): string {
    // Note: we deliberately do NOT inline the extracted text here. PDF/image
    // content is embedded into ChromaDB at upload time and the backend's
    // document_parser agent retrieves the relevant passages on every turn
    // (including follow-ups). Inlining the excerpt would (a) waste tokens
    // on every subsequent turn the user reads chat history, (b) fail on
    // follow-up questions once the excerpt scrolls out of the context
    // window, and (c) duplicate work the agent already does correctly.
    //
    // We only emit a compact, machine-readable list of filenames so the
    // strategist knows which files exist and can route doc-related
    // questions to document_parser. Plain-text attachments still inline
    // their excerpt because they are not indexed in Chroma.
    if (atts.length === 0) return "";
    const blocks = atts.map((a) => {
      const header = `**${a.name}** _(${humanSize(a.size)}${a.summary ? ` · ${a.summary}` : ""})_`;
      const isIndexed = a.kind === "pdf" || a.kind === "image";
      if (!isIndexed && a.excerpt) {
        const fence = a.name.match(/\.(json|ya?ml|toml|ini)$/i) ? a.name.split(".").pop()!.toLowerCase() : "";
        return `${header}\n\`\`\`${fence}\n${a.excerpt}\n\`\`\``;
      }
      return header;
    });
    return `\n\n📎 **${t("attach.contextHeader", { count: atts.length })}**\n${blocks.join("\n\n")}`;
  }

  async function send(text: string, replayAttachments?: MessageAttachment[]) {
    const hasReadyAttachments = attachments.some((a) => a.status === "ready");
    const replaying = replayAttachments && replayAttachments.length > 0;
    if ((!text.trim() && !hasReadyAttachments && !replaying) || streaming) return;
    if (attachments.some((a) => a.status === "uploading")) {
      toast.warning(t("attach.waitForUpload"));
      return;
    }
    const userText = text.trim();
    // Build the context sent to the agent (structured + extracted text), but keep `content` clean.
    let agentContext = "";
    let messageAttachments: MessageAttachment[] | undefined;
    if (replaying) {
      messageAttachments = replayAttachments;
      agentContext = buildAgentContextFromMeta(replayAttachments);
    } else if (hasReadyAttachments) {
      const ready = attachments.filter((a) => a.status === "ready");
      messageAttachments = ready.map<MessageAttachment>((a) => ({
        id: a.id,
        name: a.name,
        mime: a.mime,
        kind: a.kind === "other" ? "binary" : a.kind,
        size: a.size,
        summary: a.summary,
        excerpt: a.excerpt,
      }));
      agentContext = buildAgentContextFromMeta(messageAttachments);
    }
    const finalText = (userText || t("attach.implicitPrompt")) + agentContext;
    const displayContent = userText; // clean — attachments render as chips
    const userId = `u-${Date.now()}`;
    const asstId = `a-${Date.now()}`;
    lastAsstId.current = asstId;
    appendMessage(convId, {
      id: userId,
      role: "user",
      content: displayContent,
      attachments: messageAttachments,
      createdAt: Date.now(),
    });
    appendMessage(convId, { id: asstId, role: "assistant", content: "", createdAt: Date.now() });
    setInput("");
    setAttachments([]);
    setStreaming(true);
    setStoppedPrompt(null);
    inFlightPromptRef.current = finalText;
    clearAgentEvents();
    setActiveAgent(null);
    toolActivitiesRef.current = [];
    seenAgentsThisTurn.current.clear();
    toolRunsRef.current.clear();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const uiLang = (i18n.language || "en").slice(0, 2);
      for await (const event of streamChat(finalText, threadId, convId, controller.signal, displayCurrency, uiLang)) {
        switch (event.type) {
          case "token":
            appendToken(convId, lastAsstId.current!, (event.payload.text as string) ?? "");
            break;
          case "agent_start": {
            const agentName = event.payload.agent as string;
            const internal = event.payload.internal === true;
            setActiveAgent(agentName);

            // Supervisor never produces content — skip bubble logic for it.
            // Internal workers (intermediate specialists) also stay invisible;
            // their tool calls show in the activity panel but their output is
            // folded into the synthesizer's single final bubble.
            if (agentName !== "supervisor" && !internal) {
              const currentId = lastAsstId.current!;
              const currentMsgs = useChatStore.getState().messagesByConv[convId] ?? [];
              const currentBubble = currentMsgs.find((m) => m.id === currentId);
              const isUnassignedPlaceholder =
                currentBubble &&
                !currentBubble.agent &&
                currentBubble.content.length === 0;

              if (isUnassignedPlaceholder) {
                // First agent of this turn — adopt the initial placeholder bubble.
                setMessageAgent(convId, currentId, agentName);
              } else {
                // Any subsequent agent always gets its own fresh bubble,
                // even if the prior agent ended up producing no content.
                const newId = `a-${Date.now()}-${agentName}`;
                lastAsstId.current = newId;
                appendMessage(convId, {
                  id: newId,
                  role: "assistant",
                  content: "",
                  agent: agentName,
                  createdAt: Date.now(),
                });
              }
              seenAgentsThisTurn.current.add(agentName);
            }
            break;
          }
          case "agent_done":
            break;
          case "tool_call": {
            const runId = event.payload.run_id as string ?? String(Date.now());
            const tool = event.payload.tool as string;
            const args = (event.payload.args ?? {}) as Record<string, unknown>;
            toolRunsRef.current.set(runId, { tool, argsKey: stableKey(args) });
            toolActivitiesRef.current = [...toolActivitiesRef.current, { runId, tool, args, status: "running" as const }];
            break;
          }
          case "tool_result": {
            const runId = event.payload.run_id as string;
            const result = event.payload.result as string;
            const existing = toolRunsRef.current.get(runId);
            if (existing) toolRunsRef.current.set(runId, { ...existing, result });
            toolActivitiesRef.current = toolActivitiesRef.current.map((a) =>
              a.runId === runId ? { ...a, status: "done" as const, result } : a
            );
            break;
          }
          case "agent_message":
            // Badge is already set on agent_start. Generate a real LLM title once per conv.
            if (activeConv && !activeConv.title) {
              const fallback = text.slice(0, 60);
              updateTitle(convId, fallback);
              void autotitleConversation(convId, text).then((t) => {
                if (t && t !== fallback) updateTitle(convId, t);
              });
            }
            break;
          case "citations": {
            const items = (event.payload.items as ApiCitation[]) ?? [];
            const agent = event.payload.agent as string | undefined;
            // Look up the captured tool_result for each citation by matching
            // (tool name, canonical args). Multiple invocations with the same
            // args are popped FIFO so each citation gets a distinct result.
            const runs = Array.from(toolRunsRef.current.values());
            addCitations(
              convId,
              lastAsstId.current!,
              items.map((c) => {
                const key = stableKey(c.args ?? {});
                const idx = runs.findIndex(
                  (r) => r.tool === c.tool && r.argsKey === key && r.result !== undefined
                );
                let result: string | undefined;
                if (idx >= 0) {
                  result = runs[idx].result;
                  runs.splice(idx, 1);
                }
                return { ...c, agent, result };
              })
            );
            break;
          }
          case "agent_reasoning": {
            const p = event.payload as Record<string, unknown>;
            if (lastAsstId.current && typeof p.agent === "string") {
              addReasoning(convId, lastAsstId.current, {
                agent: p.agent as string,
                why_summary: typeof p.why_summary === "string" ? p.why_summary : undefined,
                key_drivers: Array.isArray(p.key_drivers) ? (p.key_drivers as Array<{ source: string; factor: string; impact: string }>) : [],
                allocation_drivers: Array.isArray(p.allocation_drivers) ? (p.allocation_drivers as Array<{ asset_class: string; drivers: Array<{ source: string; factor: string; impact: string }> }>) : undefined,
                risk_score: typeof p.risk_score === "number" ? p.risk_score : undefined,
                profile: typeof p.profile === "string" ? p.profile : undefined,
                equity_band: Array.isArray(p.equity_band) ? (p.equity_band as [number | undefined, number | undefined]) : undefined,
              });
            }
            break;
          }
          case "suggestions": {
            const items = (event.payload.items as string[]) ?? [];
            if (Array.isArray(items) && items.length > 0 && lastAsstId.current) {
              setMessageSuggestions(convId, lastAsstId.current, items.slice(0, 4));
            }
            break;
          }
          case "agent_error": {
            const agent = String(event.payload.agent ?? "agent");
            const errType = String(event.payload.type ?? "Error");
            const msg = String(event.payload.message ?? "unknown");
            appendToken(
              convId,
              lastAsstId.current!,
              `⚠️ **${agent}** failed (\`${errType}\`): ${msg}`,
            );
            break;
          }
          case "error":
            appendToken(convId, lastAsstId.current!, `\n\n_Error: ${String(event.payload.message ?? "unknown")}_`);
            break;
          case "done":
            return;
        }
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        appendToken(convId, asstId, "\n\n_Stopped by user._");
        if (inFlightPromptRef.current) setStoppedPrompt(inFlightPromptRef.current);
      } else {
        appendToken(convId, asstId, `\n\n_Error: ${(err as Error).message}_`);
      }
    } finally {
      abortRef.current = null;
      inFlightPromptRef.current = null;
      setStreaming(false);
      setActiveAgent(null);
      // Attach the turn's tool trace to the final (synthesizer) bubble so the
      // user can expand "what I did" and see each tool's result + calc cards.
      if (lastAsstId.current && toolActivitiesRef.current.length > 0) {
        setMessageSteps(convId, lastAsstId.current, toolActivitiesRef.current);
      }
      setTimeout(() => {
        clearAgentEvents();
      }, 800);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  function onPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    const files: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind !== "file") continue;
      const f = item.getAsFile();
      if (!f) continue;
      // Clipboard screenshots arrive as nameless "image.png" — give them a useful name.
      const named = f.name && f.name !== "image.png"
        ? f
        : new File([f], `pasted-${Date.now()}.${(f.type.split("/")[1] || "png")}`, { type: f.type });
      files.push(named);
    }
    if (files.length > 0) {
      e.preventDefault();
      addFiles(files);
    }
  }

  function clearChat() {
    if (streaming) return;
    if (messages.length === 0) return;
    if (!window.confirm(t("confirmClear"))) return;
    resetConv(convId);
    clearAgentEvents();
  }

  async function startRecording() {
    if (recording || transcribing) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error(t("voice.unsupported"));
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast.error(t("voice.micDenied"));
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    audioChunksRef.current = [];
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };
    rec.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop());
      const blob = new Blob(audioChunksRef.current, { type: rec.mimeType || "audio/webm" });
      if (blob.size === 0) return;
      setTranscribing(true);
      try {
        const text = await transcribeAudio(blob);
        if (text.trim()) {
          setInput((prev) => (prev ? `${prev} ${text}` : text));
          textareaRef.current?.focus();
        } else {
          toast.error(t("voice.empty"));
        }
      } catch {
        toast.error(t("voice.failed"));
      } finally {
        setTranscribing(false);
      }
    };
    mediaRecorderRef.current = rec;
    rec.start();
    setRecording(true);
  }

  function stopRecording() {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  }

  function toggleRecording() {
    if (recording) stopRecording();
    else void startRecording();
  }

  // Streaming + last assistant message empty → show "thinking" dots
  const thinkingFor = (() => {
    if (!streaming) return null;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return null;
    return last.content.length === 0 ? last.id : null;
  })();

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        {messages.length > 0 && (
          <div className="mb-3 flex items-center justify-end">
            <button
              type="button"
              onClick={clearChat}
              disabled={streaming}
              className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs text-content-muted hover:border-loss hover:text-loss disabled:opacity-30"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t("clearChat")}
            </button>
          </div>
        )}

        <div
          role="log"
          aria-live="polite"
          aria-atomic="false"
          aria-relevant="additions"
          aria-label="Conversation messages"
          className={cn(
            "flex-1 overflow-y-auto pr-2",
            messages.length === 0 ? "flex flex-col items-center justify-center" : "space-y-4",
          )}
        >
          {messages.length === 0 && (
            <div className="w-full max-w-lg text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/15 text-accent shadow-glow">
                <Sparkles className="h-6 w-6" />
              </div>
              <h1 className="text-h2 font-semibold tracking-tight">{t("coach")}</h1>
              <p className="mx-auto mt-2 max-w-sm text-body-sm text-content-muted">{t("greeting")}</p>
              <p className="mb-3 mt-7 text-overline uppercase text-content-muted">{t("tryOneOfThese")}</p>
              <div className="flex flex-wrap justify-center gap-2">
                {suggestions.map((s, i) => (
                  <button
                    type="button"
                    key={i}
                    onClick={() => send(s)}
                    className="rounded-full border border-line bg-surface-raised/50 px-3.5 py-2 text-xs text-content transition-colors hover:border-accent hover:text-accent"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => {
            const isThinking = thinkingFor === m.id;
            const isAssistant = m.role === "assistant";
            const isStreamingThis = streaming && lastAsstId.current === m.id && m.content.length > 0;
            const showCopy = isAssistant && !isThinking && m.content.length > 0;
            const timeStr = new Date(m.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
            const regenHandler = () => {
              const idx = messages.findIndex((x) => x.id === m.id);
              if (idx <= 0) return;
              const prior = messages[idx - 1];
              if (!prior || prior.role !== "user") return;
              void send(prior.content, prior.attachments);
            };
            return (
              <div
                key={m.id}
                className={cn(
                  "group relative flex w-full",
                  m.role === "user" ? "justify-end" : "justify-start"
                )}
              >
                <div
                  className={cn(
                    "flex flex-col gap-2",
                    m.role === "user"
                      ? "max-w-[75%] items-end"
                      : "w-full max-w-4xl items-stretch"
                  )}
                >
                <div
                  className={cn(
                    "relative rounded-2xl border p-4 text-sm shadow-sm",
                    m.role === "user"
                      ? "rounded-tr-md border-accent/30 bg-accent/15"
                      : "rounded-tl-md border-line bg-surface-raised"
                  )}
                >
                  {isAssistant && m.agent && (
                    <div className="mb-2"><AgentBadge name={m.agent} /></div>
                  )}
                  {showCopy && <CopyButton text={m.content} />}
                  {isThinking ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
                      <span className="text-xs text-content-muted">{activeAgent ?? t("thinking")}</span>
                    </div>
                  ) : (
                    <div
                      className={cn(
                        "prose prose-invert prose-sm max-w-[72ch]",
                        isStreamingThis && "chat-streaming-fade"
                      )}
                    >
                      {m.attachments && m.attachments.length > 0 && (
                        <MessageAttachments attachments={m.attachments} />
                      )}
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {m.content || (isAssistant ? "…" : "")}
                      </ReactMarkdown>
                      {isStreamingThis && (
                        <span className="ml-0.5 inline-block h-3 w-1.5 -translate-y-0.5 bg-accent align-middle chat-cursor-blink" />
                      )}
                    </div>
                  )}
                  {isAssistant && m.suggestions && m.suggestions.length > 0 && (
                    <div className="mt-3 flex flex-col gap-1.5 border-t border-line pt-3">
                      <span className="text-overline uppercase text-content-muted">
                        {t("tryNext")}
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {m.suggestions.map((s, i) => (
                          <button
                            key={`${m.id}-sug-${i}`}
                            type="button"
                            disabled={streaming}
                            onClick={() => send(s)}
                            className="rounded-full border border-line bg-surface-raised px-3 py-1 text-[11px] text-content hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {isAssistant && m.steps && m.steps.length > 0 && (
                    <AgentTrace
                      steps={m.steps}
                      label={(i18n.language || "en").startsWith("tr") ? "Adımlar" : "Steps"}
                    />
                  )}

                  {/* Bottom bar: actions (assistant only) + timestamp */}
                  <div className="mt-2 flex items-center justify-between">
                    {isAssistant && !isThinking && m.content.length > 0 ? (
                      <MessageActions
                        messageId={m.id}
                        threadId={threadId}
                        agent={m.agent}
                        excerpt={m.content}
                        streaming={streaming}
                        onRegenerate={regenHandler}
                      />
                    ) : (
                      <span />
                    )}
                    <p className="text-[11px] text-content-muted/90 select-none tabular-nums">
                      {timeStr}
                    </p>
                  </div>
                </div>
                </div>
              </div>
            );
          })}
          <div ref={scrollAnchor} />
        </div>

        {stoppedPrompt && !streaming && (
          <div className="mt-4 flex items-center justify-between rounded-lg border border-line bg-surface px-3 py-2 text-xs">
            <span className="text-content-muted">
              {t("responseStopped")}
            </span>
            <button
              type="button"
              onClick={() => {
                const p = stoppedPrompt;
                setStoppedPrompt(null);
                void send(p);
              }}
              className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:opacity-90"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {t("continue")}
            </button>
          </div>
        )}

        <div
          className="relative mt-4"
          onDragEnter={onDragEnter}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={onFileInput}
          />

          {attachments.length > 0 && (
            <AttachmentStrip
              attachments={attachments}
              onRemove={removeAttachment}
              onRetry={retryAttachment}
            />
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
            className={cn(
              "flex items-end gap-2 rounded-lg transition-colors",
              isDragging && "ring-2 ring-accent ring-offset-2 ring-offset-bg",
            )}
          >
            <div className="relative flex flex-1 items-end">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={streaming || attachments.length >= MAX_FILES}
                title={t("attach.upload")}
                className="absolute bottom-1.5 left-1.5 z-10 flex h-8 w-8 items-center justify-center rounded-md text-content-muted hover:bg-surface-raised hover:text-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <Paperclip className="h-4 w-4" />
              </button>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                onPaste={onPaste}
                rows={1}
                placeholder={t("placeholder")}
                className="num-0 flex-1 resize-none rounded-lg border border-content-muted/25 bg-surface py-3 pl-11 pr-4 text-sm leading-5 outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/40"
                disabled={streaming}
              />
            </div>
            {!streaming && (
              <button
                type="button"
                onClick={toggleRecording}
                disabled={transcribing}
                title={recording ? t("voice.stop") : t("voice.start")}
                aria-label={recording ? t("voice.stop") : t("voice.start")}
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-lg border transition-colors disabled:opacity-40",
                  recording
                    ? "border-loss bg-loss/15 text-loss animate-pulse"
                    : "border-line bg-surface text-content-muted hover:border-accent hover:text-accent",
                )}
              >
                {transcribing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </button>
            )}
            {streaming ? (
              <button
                type="button"
                onClick={stop}
                title={t("stopGenerating")}
                className="flex h-11 w-11 items-center justify-center rounded-lg bg-loss/90 text-white shadow-glow"
              >
                <Square className="h-4 w-4 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() && !attachments.some((a) => a.status === "ready")}
                title={t("send")}
                className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent text-accent-fg shadow-glow disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </form>

          {isDragging && (
            <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent bg-surface/95 backdrop-blur-sm">
              <UploadCloud className="h-7 w-7 text-accent" />
              <p className="text-sm font-medium text-content">
                {t("attach.dropHere")}
              </p>
              <p className="text-[11px] text-content-muted">
                {t("attach.limits", { max: humanSize(MAX_FILE_SIZE), count: MAX_FILES })}
              </p>
            </div>
          )}
        </div>
        <Disclaimer className="mt-2 text-center" />
      </div>

    </div>
  );
}

// Canonical args key — sort object keys so {a:1,b:2} and {b:2,a:1} hash the same.
function stableKey(obj: unknown): string {
  if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) return `[${obj.map(stableKey).join(",")}]`;
  const entries = Object.entries(obj as Record<string, unknown>).sort(([a], [b]) =>
    a.localeCompare(b)
  );
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableKey(v)}`).join(",")}}`;
}

function MessageActions({
  messageId,
  threadId,
  agent,
  excerpt,
  streaming,
  onRegenerate,
}: {
  messageId: string;
  threadId: string;
  agent?: string;
  excerpt: string;
  streaming: boolean;
  onRegenerate: () => void;
}) {
  const { t } = useTranslation("chat");
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [busy, setBusy] = useState(false);

  async function rate(value: "up" | "down") {
    if (busy || streaming) return;
    const next = rating === value ? null : value;
    // Optimistic UI: flip immediately, revert on failure.
    setRating(next);
    if (next === null) return; // we don't currently support clearing on the server
    setBusy(true);
    try {
      await sendFeedback({
        thread_id: threadId,
        message_id: messageId,
        rating: value,
        agent,
        excerpt: excerpt.slice(0, 400),
      });
      toast.success(value === "up" ? t("feedbackThanksUp") : t("feedbackThanksDown"));
    } catch (err) {
      setRating(rating);
      toast.error(t("feedbackSaveError", { message: (err as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  const btn =
    "flex h-7 w-7 items-center justify-center rounded-md text-content-muted transition-colors hover:bg-surface-raised disabled:opacity-30 disabled:cursor-not-allowed";

  return (
    <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      <button
        type="button"
        title={t("helpful")}
        onClick={() => rate("up")}
        disabled={busy || streaming}
        className={cn(btn, rating === "up" && "text-gain bg-surface-raised")}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        title={t("notHelpful")}
        onClick={() => rate("down")}
        disabled={busy || streaming}
        className={cn(btn, rating === "down" && "text-loss bg-surface-raised")}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        title={t("regenerate")}
        onClick={onRegenerate}
        disabled={streaming}
        className={btn}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}


function AttachmentStrip({
  attachments,
  onRemove,
  onRetry,
}: {
  attachments: Attachment[];
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const { t } = useTranslation("chat");
  return (
    <div className="mb-2 flex flex-wrap gap-2 rounded-lg border border-line bg-surface-raised/60 p-2">
      {attachments.map((a) => {
        const isUploading = a.status === "uploading";
        const isError = a.status === "error";
        return (
          <div
            key={a.id}
            className={cn(
              "group relative flex max-w-[260px] items-center gap-2 overflow-hidden rounded-md border bg-surface px-2 py-1.5 text-xs transition-colors",
              isError
                ? "border-loss/40"
                : "border-line hover:border-accent/40",
            )}
            title={a.error || a.summary || a.name}
          >
            {!isError && !isUploading && (
              <div className="group/hint absolute -right-1 -top-1 z-10">
                <div className="flex h-4 w-4 cursor-default items-center justify-center rounded-full border border-line bg-surface-raised text-[10px] font-bold text-content-muted transition-colors group-hover/hint:border-accent/50 group-hover/hint:bg-accent/10 group-hover/hint:text-accent">
                  !
                </div>
                <div className="pointer-events-none absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-line bg-surface-raised px-2.5 py-2 text-[10px] leading-snug text-content-muted opacity-0 shadow-lg transition-opacity group-hover/hint:opacity-100">
                  {t("attach.tempStorage")}
                </div>
              </div>
            )}
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                isError
                  ? "bg-loss/10 text-loss"
                  : isUploading
                    ? "bg-accent/10 text-accent"
                    : "bg-gain/10 text-gain",
              )}
            >
              {isUploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : isError ? (
                <AlertCircle className="h-3.5 w-3.5" />
              ) : (
                <KindIcon kind={a.kind} />
              )}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="truncate text-[11px] font-medium text-content">
                {a.name}
              </span>
              {isUploading ? (
                <div className="h-1 w-full overflow-hidden rounded-full bg-surface-raised">
                  <div
                    className="h-full bg-accent transition-[width] duration-200"
                    style={{ width: `${a.progress}%` }}
                  />
                </div>
              ) : isError ? (
                <span className="truncate text-[10px] text-loss">
                  {t("attach.failed")}
                </span>
              ) : (
                <span className="truncate text-[10px] text-content-muted">
                  {humanSize(a.size)}
                  {a.summary ? ` · ${a.summary}` : ""}
                </span>
              )}
            </div>
            {isError && (
              <button
                type="button"
                onClick={() => onRetry(a.id)}
                title={t("attach.retry")}
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-content-muted hover:bg-surface-raised hover:text-accent"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            )}
            <button
              type="button"
              onClick={() => onRemove(a.id)}
              title={t("attach.remove")}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-content-muted hover:bg-loss/10 hover:text-loss"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation("chat");
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(t("copied"));
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(t("copyError"));
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      title={t("copy")}
      className="absolute right-2 top-2 rounded-md p-1.5 text-content-muted opacity-0 transition group-hover:opacity-100 hover:bg-surface-raised hover:text-accent"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-gain" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

