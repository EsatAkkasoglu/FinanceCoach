import { useEffect, useRef, useState } from "react";
import { Send, Square, Trash2, Copy, Check, ChevronDown, ChevronRight, Loader2, ThumbsUp, ThumbsDown, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { streamChat, sendFeedback, autotitleConversation, type Citation as ApiCitation } from "@/lib/api";
import { parseToolResult } from "@/lib/parseToolResult";
import { useChatStore, useAgentVizStore, useConversationStore, type ToolActivity } from "@/store";
import { cn } from "@/lib/cn";
import { AgentBadge } from "./AgentBadge";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { CitationChip } from "./CitationChip";

const SUGGESTION_KEYS = [
  "suggestions.spendingSummary",
  "suggestions.nvdaDecision",
  "suggestions.goldFunds",
  "suggestions.cryptoTrends",
] as const;

interface ChatPanelProps {
  convId: string;
  threadId: string;
}

export function ChatPanel({ convId, threadId }: ChatPanelProps) {
  const { t } = useTranslation("chat");
  const {
    messagesByConv, streaming,
    appendMessage, appendToken, setMessageAgent, addCitations, setMessageSteps, setMessageSuggestions, setStreaming, resetConv,
  } = useChatStore();
  const messages = messagesByConv[convId] ?? [];
  const setAgentEvent = useAgentVizStore((s) => s.setEvent);
  const markAgentDone = useAgentVizStore((s) => s.markDone);
  const incrementAgentToolCount = useAgentVizStore((s) => s.incrementToolCount);
  const clearAgentEvents = useAgentVizStore((s) => s.clear);
  const updateTitle = useConversationStore((s) => s.updateTitle);
  const activeConv = useConversationStore((s) => s.conversations.find((c) => c.id === convId));
  const [input, setInput] = useState("");
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [toolActivities, setToolActivities] = useState<ToolActivity[]>([]);
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

  async function send(text: string) {
    if (!text.trim() || streaming) return;
    const userId = `u-${Date.now()}`;
    const asstId = `a-${Date.now()}`;
    lastAsstId.current = asstId;
    appendMessage(convId, { id: userId, role: "user", content: text, createdAt: Date.now() });
    appendMessage(convId, { id: asstId, role: "assistant", content: "", createdAt: Date.now() });
    setInput("");
    setStreaming(true);
    setStoppedPrompt(null);
    inFlightPromptRef.current = text;
    clearAgentEvents();
    setActiveAgent(null);
    setToolActivities([]);
    toolActivitiesRef.current = [];
    seenAgentsThisTurn.current.clear();
    toolRunsRef.current.clear();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of streamChat(text, threadId, convId, controller.signal)) {
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
                {SUGGESTION_KEYS.map((key) => {
                  const suggestion = t(key);
                  return (
                    <button
                      key={key}
                      onClick={() => send(suggestion)}
                      className="rounded-full border border-[hsl(var(--border))] px-3 py-1.5 text-xs hover:border-accent hover:text-accent"
                    >
                      {suggestion}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {messages.map((m) => {
            const isThinking = thinkingFor === m.id;
            const isAssistant = m.role === "assistant";
            const isStreamingThis = streaming && lastAsstId.current === m.id && m.content.length > 0;
            const showCopy = isAssistant && !isThinking && m.content.length > 0;
            const hasSteps = Boolean(isAssistant && m.steps && m.steps.length > 0);
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
                {isAssistant && (
                  <div className="mb-2">
                    {hasSteps ? (
                      <StepsPanel steps={m.steps ?? []} agent={m.agent ?? null} compact />
                    ) : (
                      m.agent && <AgentBadge name={m.agent} />
                    )}
                  </div>
                )}
                {showCopy && <CopyButton text={m.content} />}
                {isThinking ? (
                  <AgentActivity agent={activeAgent} activities={toolActivities} />
                ) : (
                  <div
                    className={cn(
                      "prose prose-invert prose-sm max-w-none whitespace-pre-wrap",
                      isStreamingThis && "chat-streaming-fade"
                    )}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {m.content || (isAssistant ? "…" : "")}
                    </ReactMarkdown>
                    {isStreamingThis && (
                      <span className="ml-0.5 inline-block h-3 w-1.5 -translate-y-0.5 bg-accent align-middle chat-cursor-blink" />
                    )}
                  </div>
                )}
                {isAssistant && m.citations && m.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-start gap-1.5 border-t border-[hsl(var(--border))] pt-3">
                    <span className="mr-1 text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">
                      {t("sources")}
                    </span>
                    {m.citations.map((c, i) => (
                      <CitationChip key={`${m.id}-${i}`} citation={c} />
                    ))}
                  </div>
                )}
                {isAssistant && !isThinking && m.content.length > 0 && (
                  <MessageActions
                    messageId={m.id}
                    threadId={threadId}
                    agent={m.agent}
                    excerpt={m.content}
                    streaming={streaming}
                    onRegenerate={() => {
                      const idx = messages.findIndex((x) => x.id === m.id);
                      if (idx <= 0) return;
                      const prior = messages[idx - 1];
                      if (!prior || prior.role !== "user") return;
                      void send(prior.content);
                    }}
                  />
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
                <p className="mt-2 text-right text-[10px] text-[hsl(var(--text-muted))]/50 select-none">
                  {new Date(m.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
                </p>
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
            placeholder={t("placeholder")}
            className="num-0 flex-1 resize-none rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-sm leading-5 outline-none focus:border-accent"
            disabled={streaming}
          />
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
              disabled={!input.trim()}
              title={t("send")}
              className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent text-accent-fg shadow-glow disabled:opacity-40"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </form>
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

const TOOL_META: Record<string, { label: string; icon: string }> = {
  get_quote:           { label: "Quote",         icon: "📈" },
  resolve_symbol:      { label: "Resolve",        icon: "🔎" },
  analyze_ticker_8dim: { label: "8-dim Analysis", icon: "🔍" },
  get_dividend_metrics:{ label: "Dividends",      icon: "💰" },
  scan_hot_trends:     { label: "Hot Scanner",    icon: "🔥" },
  scan_rumors:         { label: "Rumor Scanner",  icon: "👂" },
  search_fund:         { label: "Fund Search",    icon: "🏦" },
  get_fund_quote:      { label: "Fund Quote",     icon: "🏦" },
  get_fund_history:    { label: "Fund History",   icon: "📊" },
  list_top_funds:      { label: "Top Funds",      icon: "🏆" },
  list_holdings:       { label: "Holdings",       icon: "📋" },
  list_transactions:   { label: "Transactions",   icon: "📋" },
  add_holding:           { label: "Add Holding",    icon: "➕" },
  add_holding_by_value:  { label: "Buy by Value",   icon: "💸" },
  set_cash_balance:      { label: "Set Cash",       icon: "💵" },
  remove_holding:        { label: "Close Position", icon: "🗑️" },
  search_news:         { label: "News",           icon: "📰" },
  get_user_profile:    { label: "Profile",        icon: "👤" },
  update_risk_score:   { label: "Update Risk",    icon: "⚖️" },
  query_memory:        { label: "Memory",         icon: "🧠" },
};

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
  const meta = TOOL_META[activity.tool] ?? { label: activity.tool, icon: "⚙️" };
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
}: {
  steps: ToolActivity[];
  agent?: string | null;
  compact?: boolean;
}) {
  const { t } = useTranslation("chat");
  const [open, setOpen] = useState(false);
  const doneCount = steps.filter((s) => s.status === "done").length;
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
        {agent && (
          <span className="text-[hsl(var(--text-muted))]">
            <span className="font-medium text-accent">{agent}</span>
          </span>
        )}
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
        <div className={cn("space-y-1", compact ? "border-t border-[hsl(var(--border))] p-2" : "mt-2 pl-1") }>
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
    <div className="mt-3 flex items-center gap-1 border-t border-[hsl(var(--border))] pt-2 opacity-60 transition-opacity group-hover:opacity-100">
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

