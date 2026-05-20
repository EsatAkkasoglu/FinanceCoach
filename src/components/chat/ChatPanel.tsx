import { useEffect, useRef, useState } from "react";
import { Send, Square, Trash2, Copy, Check, ChevronDown, ChevronRight, Loader2, ThumbsUp, ThumbsDown, RotateCcw, Paperclip, X, FileText, FileSpreadsheet, FileCode, Image as ImageIcon, File as FileIcon, AlertCircle, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { streamChat, sendFeedback, autotitleConversation, parseDocument, type Citation as ApiCitation } from "@/lib/api";
import { parseToolResult } from "@/lib/parseToolResult";
import { useChatStore, useAgentVizStore, useConversationStore, useSettingsStore, type ToolActivity, type MessageAttachment } from "@/store";
import { cn } from "@/lib/cn";
import { AgentBadge } from "./AgentBadge";
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
            "group/att flex items-center gap-2 rounded-lg border border-[hsl(var(--border))]",
            "bg-[hsl(var(--surface-2))]/70 px-2.5 py-1.5 text-left",
            "transition-all duration-200 ease-out",
            "hover:-translate-y-0.5 hover:border-accent/60 hover:bg-[hsl(var(--surface-2))] hover:shadow-[0_0_0_1px_hsl(var(--accent)/0.25),0_4px_16px_-4px_hsl(var(--accent)/0.35)]",
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
            <span className="truncate max-w-[200px] text-xs font-medium text-[hsl(var(--text-primary))]">
              {a.name}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">
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
  const setAgentEvent = useAgentVizStore((s) => s.setEvent);
  const markAgentDone = useAgentVizStore((s) => s.markDone);
  const incrementAgentToolCount = useAgentVizStore((s) => s.incrementToolCount);
  const clearAgentEvents = useAgentVizStore((s) => s.clear);
  const updateTitle = useConversationStore((s) => s.updateTitle);
  const activeConv = useConversationStore((s) => s.conversations.find((c) => c.id === convId));
  const displayCurrency = useSettingsStore((s) => s.displayCurrency);
  const [input, setInput] = useState("");
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [toolActivities, setToolActivities] = useState<ToolActivity[]>([]);
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
    if (atts.length === 0) return "";
    const blocks = atts.map((a) => {
      const header = `**${a.name}** _(${humanSize(a.size)}${a.summary ? ` · ${a.summary}` : ""})_`;
      if (a.excerpt) {
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
    setToolActivities([]);
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
            setAgentEvent({ agent: agentName, status: "running", startedAt: Date.now() });
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
          case "agent_done": {
            const agentName = event.payload.agent as string;
            markAgentDone(agentName);
            break;
          }
          case "tool_call": {
            const runId = event.payload.run_id as string ?? String(Date.now());
            const tool = event.payload.tool as string;
            const args = (event.payload.args ?? {}) as Record<string, unknown>;
            const parentAgent = event.payload.agent as string | undefined;
            if (parentAgent) incrementAgentToolCount(parentAgent);
            toolRunsRef.current.set(runId, { tool, argsKey: stableKey(args) });
            setToolActivities((prev) => {
              const next = [...prev, { runId, tool, args, status: "running" as const }];
              toolActivitiesRef.current = next;
              return next;
            });
            break;
          }
          case "tool_result": {
            const runId = event.payload.run_id as string;
            const result = event.payload.result as string;
            const existing = toolRunsRef.current.get(runId);
            if (existing) {
              toolRunsRef.current.set(runId, { ...existing, result });
            }
            setToolActivities((prev) => {
              const next = prev.map((a) =>
                a.runId === runId ? { ...a, status: "done" as const, result } : a
              );
              toolActivitiesRef.current = next;
              return next;
            });
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
      // Persist completed steps into the message before clearing transient state.
      if (toolActivitiesRef.current.length > 0 && lastAsstId.current) {
        setMessageSteps(convId, lastAsstId.current, toolActivitiesRef.current);
      }
      setTimeout(() => {
        clearAgentEvents();
        setToolActivities([]);
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
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("coach")}</h1>
            <p className="text-sm text-[hsl(var(--text-muted))]">
              {t("greeting")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button
                type="button"
                onClick={clearChat}
                disabled={streaming}
                className="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:border-loss hover:text-loss disabled:opacity-30"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t("clearChat")}
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto pr-2">
          {messages.length === 0 && (
            <div className="card-muted">
              <p className="mb-3 text-sm text-[hsl(var(--text-muted))]">{t("tryOneOfThese")}</p>
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => send(s)}
                    className="rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-xs hover:border-accent hover:text-accent"
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
            const hasSteps = Boolean(isAssistant && m.steps && m.steps.length > 0);
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
                      : "w-full max-w-3xl items-stretch"
                  )}
                >
                {/* Steps strip — outside the bubble, above it */}
                {isAssistant && hasSteps && (
                  <StepsPanel steps={m.steps ?? []} agent={m.agent ?? null} strip />
                )}

                <div
                  className={cn(
                    "relative rounded-2xl border p-4 text-sm shadow-sm",
                    m.role === "user"
                      ? "rounded-tr-md border-accent/30 bg-accent/15"
                      : "rounded-tl-md border-[hsl(var(--border))] bg-[hsl(var(--surface-2))]"
                  )}
                >
                  {/* Badge only when there are no steps */}
                  {isAssistant && !hasSteps && m.agent && (
                    <div className="mb-2"><AgentBadge name={m.agent} /></div>
                  )}
                  {showCopy && <CopyButton text={m.content} />}
                  {isThinking ? (
                    <AgentActivity agent={activeAgent} activities={toolActivities} />
                  ) : (
                    <div
                      className={cn(
                        "prose prose-invert prose-sm max-w-none",
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
                    <div className="mt-3 flex flex-col gap-1.5 border-t border-[hsl(var(--border))] pt-3">
                      <span className="text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">
                        {t("tryNext")}
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {m.suggestions.map((s, i) => (
                          <button
                            key={`${m.id}-sug-${i}`}
                            type="button"
                            disabled={streaming}
                            onClick={() => send(s)}
                            className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-[11px] text-[hsl(var(--text-primary))] hover:border-accent hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    </div>
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
                    <p className="text-[10px] text-[hsl(var(--text-muted))]/50 select-none">
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
          <div className="mt-4 flex items-center justify-between rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-3 py-2 text-xs">
            <span className="text-[hsl(var(--text-muted))]">
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
              isDragging && "ring-2 ring-accent ring-offset-2 ring-offset-[hsl(var(--bg))]",
            )}
          >
            <div className="relative flex flex-1 items-end">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={streaming || attachments.length >= MAX_FILES}
                title={t("attach.upload")}
                className="absolute bottom-1.5 left-1.5 z-10 flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
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
                className="num-0 flex-1 resize-none rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] py-3 pl-11 pr-4 text-sm leading-5 outline-none focus:border-accent"
                disabled={streaming}
              />
            </div>
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
            <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent bg-[hsl(var(--surface))]/95 backdrop-blur-sm">
              <UploadCloud className="h-7 w-7 text-accent" />
              <p className="text-sm font-medium text-[hsl(var(--text-primary))]">
                {t("attach.dropHere")}
              </p>
              <p className="text-[11px] text-[hsl(var(--text-muted))]">
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

// ─── AgentActivity ────────────────────────────────────────────────────────────

const TOOL_ICONS: Record<string, string> = {
  get_quote: "📈",
  resolve_symbol: "🔎",
  analyze_ticker_8dim: "🔍",
  get_dividend_metrics: "💰",
  scan_hot_trends: "🔥",
  get_us_movers: "🇺🇸",
  get_bist_movers: "🇹🇷",
  scan_rumors: "👂",
  search_fund: "🏦",
  get_fund_quote: "🏦",
  get_fund_history: "📊",
  list_top_funds: "🏆",
  list_holdings: "📋",
  list_transactions: "📋",
  add_holding: "➕",
  add_holding_by_value: "💸",
  set_cash_balance: "💵",
  remove_holding: "🗑️",
  search_news: "📰",
  get_user_profile: "👤",
  update_risk_score: "⚖️",
  query_memory: "🧠",
};

function useToolMeta(tool: string): { label: string; icon: string } {
  const { t } = useTranslation("chat");
  const icon = TOOL_ICONS[tool] ?? "⚙️";
  const label = t(`tools.${tool}`, { defaultValue: tool });
  return { label, icon };
}

// Render parsed result as a clean table — scalar fields + first-level arrays.
function ResultView({ data, tool }: { data: unknown; tool?: string }) {
  const { t } = useTranslation("chat");
  if (data === null || data === undefined) return null;

  // ── Specialized inline visualizations for well-known tools ──────────────
  if (tool === "get_quote" && isRecord(data) && typeof data.price === "number") {
    return <QuoteCard quote={data} />;
  }
  if (
    (tool === "analyze_ticker_8dim" || tool === "analyze_ticker") &&
    isRecord(data) &&
    isRecord(data.dimensions)
  ) {
    return <EightDimView result={data} />;
  }

  if (typeof data === "string") {
    return (
      <p className="text-[11px] leading-relaxed text-[hsl(var(--text-muted))]">
        {data.length > 300 ? data.slice(0, 300) + "…" : data}
      </p>
    );
  }

  if (Array.isArray(data)) {
    if (data.length === 0) {
      return (
        <p className="text-[11px] italic text-[hsl(var(--text-muted))]">{t("noResults")}</p>
      );
    }
    // Array of objects → render as headline-style list (news, search hits, etc.)
    if (typeof data[0] === "object" && data[0] !== null) {
      const items = (data as Record<string, unknown>[]).slice(0, 6);
      return (
        <ul className="space-y-1.5">
          {items.map((item, i) => {
            const title = (item.title || item.headline || item.name || item.symbol || item.ticker) as
              | string
              | undefined;
            const url = (item.url || item.link) as string | undefined;
            const meta: string[] = [];
            if (item.source) meta.push(String(item.source));
            if (item.published_at) meta.push(String(item.published_at).slice(0, 16));
            if (item.sentiment) meta.push(String(item.sentiment));
            const summary = (item.summary || item.description) as string | undefined;
            return (
              <li
                key={i}
                className="rounded border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2"
              >
                {title && (url
                  ? <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] font-medium leading-snug text-[hsl(var(--text-primary))] hover:text-accent hover:underline underline-offset-2"
                    >
                      {title}
                    </a>
                  : <p className="text-[11px] font-medium leading-snug text-[hsl(var(--text-primary))]">
                      {title}
                    </p>
                )}
                {meta.length > 0 && (
                  <p className="mt-0.5 text-[10px] text-[hsl(var(--text-muted))]">
                    {meta.join(" · ")}
                  </p>
                )}
                {summary && (
                  <p className="mt-1 text-[10px] leading-snug text-[hsl(var(--text-muted))] line-clamp-2">
                    {summary}
                  </p>
                )}
                {!title && !summary && (
                  <p className="text-[10px] text-[hsl(var(--text-muted))]">
                    {JSON.stringify(item).slice(0, 120)}
                  </p>
                )}
              </li>
            );
          })}
          {data.length > items.length && (
            <li className="text-[10px] text-[hsl(var(--text-muted))]">
              +{data.length - items.length} more
            </li>
          )}
        </ul>
      );
    }
    // Array of scalars → pill list
    return (
      <div className="flex flex-wrap gap-1">
        {(data as unknown[]).slice(0, 12).map((v, i) => (
          <span
            key={i}
            className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-2 py-0.5 text-[10px] text-[hsl(var(--text-primary))]"
          >
            {String(v)}
          </span>
        ))}
        {data.length > 12 && (
          <span className="text-[10px] text-[hsl(var(--text-muted))] self-center">
            +{data.length - 12} more
          </span>
        )}
      </div>
    );
  }

  if (typeof data !== "object") {
    return (
      <p className="font-mono text-[11px] text-[hsl(var(--text-muted))]">
        {String(data).slice(0, 300)}
      </p>
    );
  }

  const obj = data as Record<string, unknown>;

  if (Array.isArray(obj.top_trending)) {
    return <HotTrendsView scanTime={obj.scan_time} trends={obj.top_trending} />;
  }

  // Separate scalars, objects (nested), arrays
  const scalars = Object.entries(obj).filter(
    ([, v]) => v !== null && v !== undefined && typeof v !== "object"
  );
  const arrays = Object.entries(obj).filter(([, v]) => Array.isArray(v));

  const SKIP_KEYS = new Set(["timestamp", "tool_call_id"]);

  const displayScalars = scalars
    .filter(([k]) => !SKIP_KEYS.has(k))
    .slice(0, 10);

  return (
    <div className="space-y-3">
      {displayScalars.length > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
          {displayScalars.map(([k, v]) => {
            const raw = String(v);
            const display = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
            const isNumeric = typeof v === "number";
            return (
              <div key={k} className="flex flex-col gap-0.5">
                <span className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                  {k.replace(/_/g, " ")}
                </span>
                <span
                  className={cn(
                    "text-[11px] font-medium leading-tight",
                    isNumeric ? "tabular-nums text-[hsl(var(--text-primary))]" : "text-[hsl(var(--text-primary))]"
                  )}
                >
                  {display}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {arrays.slice(0, 3).map(([k, v]) => {
        const items = (v as unknown[]).slice(0, 6);
        return (
          <div key={k}>
            <p className="mb-1.5 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
              {k.replace(/_/g, " ")}
            </p>
            <div className="flex flex-wrap gap-1">
              {items.map((item, i) => {
                let label: string;
                if (typeof item === "object" && item !== null) {
                  const o = item as Record<string, unknown>;
                  // Show symbol + first meaningful value
                  const sym = o.symbol ?? o.ticker ?? o.name ?? "";
                  const val = o.price ?? o.mentions ?? o.score ?? "";
                  label = sym ? `${sym}${val !== "" ? ` · ${val}` : ""}` : JSON.stringify(item).slice(0, 40);
                } else {
                  label = String(item);
                }
                return (
                  <span
                    key={i}
                    className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-2 py-0.5 text-[10px] text-[hsl(var(--text-primary))]"
                  >
                    {label}
                  </span>
                );
              })}
              {(v as unknown[]).length > 6 && (
                <span className="text-[10px] text-[hsl(var(--text-muted))] self-center">
                  +{(v as unknown[]).length - 6} more
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Compact price tile for get_quote: big price, colored change %, ticker chip.
function QuoteCard({ quote }: { quote: Record<string, unknown> }) {
  const price = Number(quote.price ?? 0);
  const changePct = Number(quote.change_pct ?? 0);
  const ticker = String(quote.ticker ?? "");
  const currency = String(quote.currency ?? "USD");
  const up = changePct >= 0;
  // Visual scale: clamp to ±10% for the bar fill so big moves don't blow out the layout.
  const barPct = Math.min(Math.abs(changePct) / 10, 1) * 100;

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            {ticker || "Quote"}
          </p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums text-[hsl(var(--text-primary))]">
            {price.toLocaleString(undefined, { maximumFractionDigits: 4 })}
            <span className="ml-1 text-[10px] font-normal text-[hsl(var(--text-muted))]">
              {currency}
            </span>
          </p>
        </div>
        <div
          className={cn(
            "rounded-md px-2 py-1 text-xs font-semibold tabular-nums",
            up ? "bg-gain/10 text-gain" : "bg-loss/10 text-loss"
          )}
        >
          {up ? "▲" : "▼"} {changePct.toFixed(2)}%
        </div>
      </div>
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
        <div
          className={cn("h-full", up ? "bg-gain" : "bg-loss")}
          style={{ width: `${barPct}%` }}
        />
      </div>
    </div>
  );
}

// Horizontal-bar overview for analyze_ticker_8dim: each dimension's score.
function EightDimView({ result }: { result: Record<string, unknown> }) {
  const dimensions = result.dimensions as Record<string, unknown> | undefined;
  if (!dimensions) return null;
  const score = typeof result.score === "number" ? result.score : null;
  const recommendation = typeof result.recommendation === "string" ? result.recommendation : null;
  const entries = Object.entries(dimensions).slice(0, 8);

  function dimScore(v: unknown): number | null {
    if (typeof v === "number") return v;
    if (isRecord(v) && typeof v.score === "number") return v.score;
    return null;
  }

  return (
    <div className="space-y-3">
      {(score !== null || recommendation) && (
        <div className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2">
          {score !== null && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                Score
              </p>
              <p className="text-base font-semibold tabular-nums text-[hsl(var(--text-primary))]">
                {score.toFixed(1)}
              </p>
            </div>
          )}
          {recommendation && (
            <div className="ml-auto">
              <span
                className={cn(
                  "rounded-md px-2 py-1 text-[11px] font-semibold uppercase",
                  recommendation === "BUY" && "bg-gain/15 text-gain",
                  recommendation === "SELL" && "bg-loss/15 text-loss",
                  recommendation === "HOLD" && "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-primary))]"
                )}
              >
                {recommendation}
              </span>
            </div>
          )}
        </div>
      )}
      <div className="space-y-1.5">
        {entries.map(([name, v]) => {
          const s = dimScore(v);
          const pct = s === null ? 0 : Math.max(0, Math.min(100, s));
          return (
            <div key={name} className="grid grid-cols-[110px_1fr_36px] items-center gap-2">
              <span className="text-[10px] capitalize text-[hsl(var(--text-muted))]">
                {name.replace(/_/g, " ")}
              </span>
              <div className="h-1.5 overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
                <div
                  className={cn(
                    "h-full",
                    pct >= 66 ? "bg-gain" : pct >= 33 ? "bg-accent" : "bg-loss"
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-right text-[10px] tabular-nums text-[hsl(var(--text-muted))]">
                {s === null ? "—" : s.toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function HotTrendsView({ scanTime, trends }: { scanTime: unknown; trends: unknown[] }) {
  const items = trends.filter(isRecord).slice(0, 8);

  return (
    <div className="space-y-2">
      {typeof scanTime === "string" && (
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
            Scan time
          </span>
          <span className="text-[11px] font-medium text-[hsl(var(--text-primary))]">
            {scanTime}
          </span>
        </div>
      )}
      <div className="grid gap-1.5 sm:grid-cols-2">
        {items.map((item, i) => {
          const symbol = String(item.symbol ?? item.ticker ?? `#${i + 1}`);
          const mentions = item.mentions;
          const sources = Array.isArray(item.sources) ? item.sources.map(String) : [];
          const signals = Array.isArray(item.signals) ? item.signals.map(String) : [];
          const signalText = signals.join(" ");
          const signalClass = signalText.toLowerCase().includes("bullish")
            ? "border-gain/30 bg-gain/10 text-gain"
            : signalText.toLowerCase().includes("bearish") || signalText.toLowerCase().includes("dump")
              ? "border-loss/30 bg-loss/10 text-loss"
              : "border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]";

          return (
            <div
              key={`${symbol}-${i}`}
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] font-semibold text-accent">{symbol}</span>
                {mentions !== undefined && (
                  <span className="rounded bg-[hsl(var(--surface-2))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))]">
                    {String(mentions)} mentions
                  </span>
                )}
              </div>
              {signals.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {signals.slice(0, 3).map((signal) => (
                    <span key={signal} className={cn("rounded px-1.5 py-0.5 text-[10px]", signalClass)}>
                      {signal}
                    </span>
                  ))}
                </div>
              )}
              {sources.length > 0 && (
                <p className="mt-1 text-[10px] leading-snug text-[hsl(var(--text-muted))]">
                  {sources.slice(0, 3).join(" · ")}
                </p>
              )}
            </div>
          );
        })}
      </div>
      {trends.length > items.length && (
        <p className="text-[10px] text-[hsl(var(--text-muted))]">
          +{trends.length - items.length} more
        </p>
      )}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function ArgPills({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args).filter(
    ([, v]) => v !== undefined && v !== null && v !== ""
  );
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="rounded bg-[hsl(var(--surface))] border border-[hsl(var(--border))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))]"
        >
          <span className="font-medium text-[hsl(var(--text-primary))]">{k}</span>
          {" "}
          {String(v).slice(0, 40)}
        </span>
      ))}
    </div>
  );
}

function ToolRow({ activity }: { activity: ToolActivity }) {
  const { t } = useTranslation("chat");
  const [open, setOpen] = useState(false);
  const meta = useToolMeta(activity.tool);
  const parsed = activity.result ? parseToolResult(activity.result) : null;

  // Primary arg value for the header preview (first non-empty value)
  const primaryArg = Object.values(activity.args).find(
    (v) => v !== undefined && v !== null && v !== ""
  );

  return (
    <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-white/5 transition-colors"
      >
        {/* status */}
        <span className="shrink-0">
          {activity.status === "running" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
          ) : (
            <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gain/20 text-gain">
              <Check className="h-2.5 w-2.5" />
            </span>
          )}
        </span>

        {/* icon + label */}
        <span className="text-sm leading-none">{meta.icon}</span>
        <span className="text-[12px] font-medium text-[hsl(var(--text-primary))]">{meta.label}</span>

        {/* primary arg chip */}
        {primaryArg !== undefined && (
          <span className="rounded bg-[hsl(var(--surface))] border border-[hsl(var(--border))] px-1.5 py-0.5 text-[10px] font-mono text-accent">
            {String(primaryArg).slice(0, 30)}
          </span>
        )}

        <span className="ml-auto shrink-0 text-[hsl(var(--text-muted))]">
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
      </button>

      {open && (
        <div className="border-t border-[hsl(var(--border))] px-3 py-3 space-y-3">
          {/* args */}
          {Object.keys(activity.args).length > 0 && (
            <div>
              <p className="mb-1.5 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                {t("input")}
              </p>
              <ArgPills args={activity.args} />
            </div>
          )}

          {/* result */}
          {parsed !== null ? (
            <div>
              <p className="mb-1.5 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">
                {t("result")}
              </p>
              <ResultView data={parsed} tool={activity.tool} />
            </div>
          ) : activity.status === "running" ? (
            <p className="text-[11px] italic text-[hsl(var(--text-muted))]">{t("fetching")}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function AgentActivity({
  agent,
  activities,
}: {
  agent: string | null;
  activities: ToolActivity[];
}) {
  const { t } = useTranslation("chat");
  const runningCount = activities.filter((a) => a.status === "running").length;
  const doneCount = activities.filter((a) => a.status === "done").length;

  return (
    <div className="space-y-3">
      {/* header */}
      <div className="flex items-center gap-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
        <span className="text-[12px] font-medium text-[hsl(var(--text-primary))]">
          {agent ?? t("thinking")}
        </span>
        {activities.length > 0 && (
          <span className="ml-auto text-[10px] text-[hsl(var(--text-muted))]">
            {runningCount > 0
              ? t("toolsProgress", { done: doneCount, total: activities.length })
              : t("toolsDone", { count: doneCount })}
          </span>
        )}
      </div>

      {/* tool rows */}
      {activities.length > 0 && (
        <div className="space-y-1.5">
          {activities.map((a) => (
            <ToolRow key={a.runId} activity={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function StepsPanel({
  steps,
  agent,
  compact = false,
  strip = false,
}: {
  steps: ToolActivity[];
  agent?: string | null;
  compact?: boolean;
  strip?: boolean;
}) {
  const { t } = useTranslation("chat");
  const [open, setOpen] = useState(false);
  const doneCount = steps.filter((s) => s.status === "done").length;

  if (strip) {
    return (
      <div className={cn(open && "mb-1")}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text-primary))] transition-colors py-0.5"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {agent && <AgentBadge name={agent} className="scale-90 origin-left" />}
          <span className="tabular-nums">{t("toolsProgress", { done: doneCount, total: steps.length })}</span>
        </button>
        {open && (
          <div className="mt-2 w-full space-y-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))]/40 p-2 overflow-x-auto">
            {steps.map((a) => (
              <ToolRow key={a.runId} activity={a} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        compact
          ? "rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))]"
          : "mt-3 border-t border-[hsl(var(--border))] pt-3"
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 transition-colors",
          compact
            ? "px-3 py-2 text-left hover:bg-white/5"
            : "text-[10px] text-[hsl(var(--text-muted))] hover:text-accent"
        )}
      >
        <span className="flex items-center gap-1">
          {open ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          <span className="uppercase tracking-wide font-medium">{t("agentSteps")}</span>
        </span>
        {agent && <AgentBadge name={agent} />}
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5",
            compact ? "bg-[hsl(var(--surface))]" : "bg-[hsl(var(--surface-2))]"
          )}
        >
          {t("toolsProgress", { done: doneCount, total: steps.length })}
        </span>
      </button>
      {open && (
        <div className={cn("space-y-1", compact ? "border-t border-[hsl(var(--border))] p-2" : "mt-2 pl-1")}>
          {steps.map((a) => (
            <ToolRow key={a.runId} activity={a} />
          ))}
        </div>
      )}
    </div>
  );
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
    "flex h-7 w-7 items-center justify-center rounded-md text-[hsl(var(--text-muted))] transition-colors hover:bg-[hsl(var(--surface-2))] disabled:opacity-30 disabled:cursor-not-allowed";

  return (
    <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      <button
        type="button"
        title={t("helpful")}
        onClick={() => rate("up")}
        disabled={busy || streaming}
        className={cn(btn, rating === "up" && "text-gain bg-[hsl(var(--surface-2))]")}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        title={t("notHelpful")}
        onClick={() => rate("down")}
        disabled={busy || streaming}
        className={cn(btn, rating === "down" && "text-loss bg-[hsl(var(--surface-2))]")}
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
    <div className="mb-2 flex flex-wrap gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))]/60 p-2">
      {attachments.map((a) => {
        const isUploading = a.status === "uploading";
        const isError = a.status === "error";
        return (
          <div
            key={a.id}
            className={cn(
              "group relative flex max-w-[260px] items-center gap-2 overflow-hidden rounded-md border bg-[hsl(var(--surface))] px-2 py-1.5 text-xs transition-colors",
              isError
                ? "border-loss/40"
                : "border-[hsl(var(--border))] hover:border-accent/40",
            )}
            title={a.error || a.summary || a.name}
          >
            {!isError && !isUploading && (
              <div className="group/hint absolute -right-1 -top-1 z-10">
                <div className="flex h-4 w-4 cursor-default items-center justify-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] text-[9px] font-bold text-[hsl(var(--text-muted))] transition-colors group-hover/hint:border-accent/50 group-hover/hint:bg-accent/10 group-hover/hint:text-accent">
                  !
                </div>
                <div className="pointer-events-none absolute bottom-full right-0 mb-1.5 w-52 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2.5 py-2 text-[10px] leading-snug text-[hsl(var(--text-muted))] opacity-0 shadow-lg transition-opacity group-hover/hint:opacity-100">
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
              <span className="truncate text-[11px] font-medium text-[hsl(var(--text-primary))]">
                {a.name}
              </span>
              {isUploading ? (
                <div className="h-1 w-full overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
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
                <span className="truncate text-[10px] text-[hsl(var(--text-muted))]">
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
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-accent"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            )}
            <button
              type="button"
              onClick={() => onRemove(a.id)}
              title={t("attach.remove")}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-[hsl(var(--text-muted))] hover:bg-loss/10 hover:text-loss"
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
      className="absolute right-2 top-2 rounded-md p-1.5 text-[hsl(var(--text-muted))] opacity-0 transition group-hover:opacity-100 hover:bg-[hsl(var(--surface-2))] hover:text-accent"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-gain" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

