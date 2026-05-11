import { useEffect, useRef, useState } from "react";
import { Send, Square, Trash2, Copy, Check, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamChat, type Citation as ApiCitation } from "@/lib/api";
import { useChatStore, useAgentVizStore, useConversationStore } from "@/store";
import { cn } from "@/lib/cn";
import { AgentGraph } from "./AgentGraph";
import { AgentBadge } from "./AgentBadge";
import { CitationChip } from "./CitationChip";

interface ToolActivity {
  runId: string;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done";
  result?: string;
}

const SUGGESTIONS = [
  "Summarize my spending this month",
  "Should I buy more NVDA?",
  "Altın fonlarından hangileri var?",
  "What's trending in crypto today?",
];

interface ChatPanelProps {
  convId: string;
  threadId: string;
}

export function ChatPanel({ convId, threadId }: ChatPanelProps) {
  const {
    messagesByConv, streaming,
    appendMessage, appendToken, setMessageAgent, addCitations, setStreaming, resetConv,
  } = useChatStore();
  const messages = messagesByConv[convId] ?? [];
  const setAgentEvent = useAgentVizStore((s) => s.setEvent);
  const clearAgentEvents = useAgentVizStore((s) => s.clear);
  const updateTitle = useConversationStore((s) => s.updateTitle);
  const activeConv = useConversationStore((s) => s.conversations.find((c) => c.id === convId));
  const [input, setInput] = useState("");
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [toolActivities, setToolActivities] = useState<ToolActivity[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastAsstId = useRef<string | null>(null);

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

  async function send(text: string) {
    if (!text.trim() || streaming) return;
    const userId = `u-${Date.now()}`;
    const asstId = `a-${Date.now()}`;
    lastAsstId.current = asstId;
    appendMessage(convId, { id: userId, role: "user", content: text, createdAt: Date.now() });
    appendMessage(convId, { id: asstId, role: "assistant", content: "", createdAt: Date.now() });
    setInput("");
    setStreaming(true);
    clearAgentEvents();
    setActiveAgent(null);
    setToolActivities([]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of streamChat(text, threadId, convId, controller.signal)) {
        switch (event.type) {
          case "token":
            appendToken(convId, asstId, (event.payload.text as string) ?? "");
            break;
          case "agent_start": {
            const agentName = event.payload.agent as string;
            setAgentEvent({ agent: agentName, status: "running", startedAt: Date.now() });
            setActiveAgent(agentName);
            break;
          }
          case "agent_done": {
            const agentName = event.payload.agent as string;
            setAgentEvent({ agent: agentName, status: "done", startedAt: Date.now() });
            break;
          }
          case "tool_call": {
            const runId = event.payload.run_id as string ?? String(Date.now());
            setToolActivities((prev) => [
              ...prev,
              {
                runId,
                tool: event.payload.tool as string,
                args: (event.payload.args ?? {}) as Record<string, unknown>,
                status: "running",
              },
            ]);
            break;
          }
          case "tool_result": {
            const runId = event.payload.run_id as string;
            setToolActivities((prev) =>
              prev.map((a) =>
                a.runId === runId
                  ? { ...a, status: "done", result: event.payload.result as string }
                  : a
              )
            );
            break;
          }
          case "agent_message":
            setMessageAgent(convId, asstId, event.payload.agent as string);
            // Auto-update sidebar title from first assistant reply if still untitled
            if (activeConv && !activeConv.title) {
              updateTitle(convId, text.slice(0, 60));
            }
            break;
          case "citations": {
            const items = (event.payload.items as ApiCitation[]) ?? [];
            const agent = event.payload.agent as string | undefined;
            addCitations(
              convId,
              asstId,
              items.map((c) => ({ ...c, agent }))
            );
            break;
          }
          case "error":
            appendToken(convId, asstId, `\n\n_Error: ${String(event.payload.message ?? "unknown")}_`);
            break;
          case "done":
            return;
        }
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        appendToken(convId, asstId, "\n\n_Stopped by user._");
      } else {
        appendToken(convId, asstId, `\n\n_Error: ${(err as Error).message}_`);
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      setActiveAgent(null);
      setTimeout(() => {
        clearAgentEvents();
        setToolActivities([]);
      }, 3000);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  function clearChat() {
    if (streaming) return;
    if (messages.length === 0) return;
    if (!window.confirm("Clear the entire chat history?")) return;
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
    <div className="flex h-full gap-6">
      {/* LEFT: chat column */}
      <div className="flex flex-1 min-w-0 flex-col">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Coach</h1>
            <p className="text-sm text-[hsl(var(--text-muted))]">
              Ask anything about your finances. Sources are cited under each answer.
            </p>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={clearChat}
              disabled={streaming}
              className="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:border-loss hover:text-loss disabled:opacity-30"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear chat
            </button>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto pr-2">
          {messages.length === 0 && (
            <div className="card-muted">
              <p className="mb-3 text-sm text-[hsl(var(--text-muted))]">Try one of these:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
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
            return (
              <div
                key={m.id}
                className={cn(
                  "group relative max-w-3xl rounded-xl border p-4 text-sm",
                  m.role === "user"
                    ? "ml-auto border-accent-muted bg-accent-muted/40"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--surface))]"
                )}
              >
                {isAssistant && m.agent && (
                  <div className="mb-2">
                    <AgentBadge name={m.agent} />
                  </div>
                )}
                {showCopy && <CopyButton text={m.content} />}
                {isThinking ? (
                  <AgentActivity agent={activeAgent} activities={toolActivities} />
                ) : (
                  <div className="prose prose-invert prose-sm max-w-none whitespace-pre-wrap">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {m.content || (isAssistant ? "…" : "")}
                    </ReactMarkdown>
                    {isStreamingThis && (
                      <span className="ml-0.5 inline-block h-3 w-1.5 -translate-y-0.5 animate-pulse bg-accent align-middle" />
                    )}
                  </div>
                )}
                {isAssistant && m.citations && m.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-start gap-1.5 border-t border-[hsl(var(--border))] pt-3">
                    <span className="mr-1 text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">
                      Sources
                    </span>
                    {m.citations.map((c, i) => (
                      <CitationChip key={`${m.id}-${i}`} citation={c} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          <div ref={scrollAnchor} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
          className="mt-4 flex items-end gap-2"
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Ask your coach… (Shift+Enter for newline)"
            className="num-0 flex-1 resize-none rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-sm leading-5 outline-none focus:border-accent"
            disabled={streaming}
          />
          {streaming ? (
            <button
              type="button"
              onClick={stop}
              title="Stop generating"
              className="flex h-11 w-11 items-center justify-center rounded-lg bg-loss/90 text-white shadow-glow"
            >
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              title="Send (Enter)"
              className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent text-accent-fg shadow-glow disabled:opacity-40"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </form>
      </div>

      {/* RIGHT: agent graph rail */}
      <div className="hidden w-[460px] shrink-0 lg:block">
        <AgentGraph />
      </div>
    </div>
  );
}

// ─── AgentActivity (replaces ThinkingDots) ────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  get_quote: "Quote",
  resolve_symbol: "Resolve",
  analyze_ticker_8dim: "8-dim Analysis",
  get_dividend_metrics: "Dividends",
  scan_hot_trends: "Hot Scanner",
  scan_rumors: "Rumor Scanner",
  search_fund: "Fund Search",
  get_fund_quote: "Fund Quote",
  get_fund_history: "Fund History",
  list_top_funds: "Top Funds",
  list_holdings: "Holdings",
  list_transactions: "Transactions",
  search_news: "News Search",
  get_user_profile: "Profile",
  update_risk_score: "Update Risk",
  query_memory: "Memory",
};

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join("  ·  ");
}

function ToolRow({ activity }: { activity: ToolActivity }) {
  const [open, setOpen] = useState(false);
  const label = TOOL_LABELS[activity.tool] ?? activity.tool;
  const argsStr = formatArgs(activity.args);

  return (
    <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-white/5 transition-colors"
      >
        {/* status icon */}
        <span className="shrink-0">
          {activity.status === "running" ? (
            <Loader2 className="h-3 w-3 animate-spin text-accent" />
          ) : (
            <span className="inline-block h-3 w-3 rounded-full bg-gain/70 flex items-center justify-center">
              <span className="block h-1.5 w-1.5 rounded-full bg-gain" />
            </span>
          )}
        </span>

        {/* tool name */}
        <code className="text-[11px] font-mono font-medium text-accent">{label}</code>

        {/* inline args preview */}
        {argsStr && (
          <span className="ml-1 truncate text-[10px] text-[hsl(var(--text-muted))]">
            {argsStr}
          </span>
        )}

        <span className="ml-auto shrink-0 text-[hsl(var(--text-muted))]">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      </button>

      {open && (
        <div className="border-t border-[hsl(var(--border))] px-3 py-2 space-y-1.5">
          {/* args */}
          {Object.keys(activity.args).length > 0 && (
            <div>
              <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">Input</p>
              <pre className="font-mono text-[10px] text-[hsl(var(--text-muted))] whitespace-pre-wrap">
                {JSON.stringify(activity.args, null, 2)}
              </pre>
            </div>
          )}
          {/* result */}
          {activity.result && (
            <div>
              <p className="mb-1 text-[9px] uppercase tracking-widest text-[hsl(var(--text-muted))]">Output</p>
              <pre className="font-mono text-[10px] text-gain/80 whitespace-pre-wrap break-all">
                {activity.result}
              </pre>
            </div>
          )}
          {activity.status === "running" && !activity.result && (
            <p className="text-[10px] text-[hsl(var(--text-muted))] italic">çalışıyor…</p>
          )}
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
  return (
    <div className="space-y-2">
      {/* header: pulsing dots + agent name */}
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
        <span className="ml-2 text-xs text-[hsl(var(--text-muted))]">
          {agent ? (
            <>
              <span className="font-medium text-accent">{agent}</span>
              <span> çalışıyor…</span>
            </>
          ) : (
            "düşünüyor…"
          )}
        </span>
      </div>

      {/* tool call rows */}
      {activities.length > 0 && (
        <div className="space-y-1 pl-1">
          {activities.map((a) => (
            <ToolRow key={a.runId} activity={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy — clipboard blocked");
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy message"
      className="absolute right-2 top-2 rounded-md p-1.5 text-[hsl(var(--text-muted))] opacity-0 transition group-hover:opacity-100 hover:bg-[hsl(var(--surface-2))] hover:text-accent"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-gain" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}
