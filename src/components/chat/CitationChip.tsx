import { useState } from "react";
import { Code2, Database, ChevronDown, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { parseToolResult } from "@/lib/parseToolResult";
import type { Citation } from "@/store";

const TOOL_META: Record<string, { label: string; previewKey?: string }> = {
  get_quote: { label: "Quote", previewKey: "ticker" },
  resolve_symbol: { label: "Resolve", previewKey: "name" },
  list_supported_categories: { label: "Categories" },
  analyze_ticker_8dim: { label: "8-dim Analysis", previewKey: "ticker" },
  get_dividend_metrics: { label: "Dividends", previewKey: "ticker" },
  scan_hot_trends: { label: "Hot Scanner" },
  scan_rumors: { label: "Rumor Scanner" },
  search_fund: { label: "Fund Search", previewKey: "query" },
  get_fund_quote: { label: "Fund Quote", previewKey: "code" },
  get_fund_history: { label: "Fund History", previewKey: "code" },
  list_top_funds: { label: "Top Funds", previewKey: "metric" },
  list_holdings: { label: "Holdings" },
  list_transactions: { label: "Transactions" },
  search_news: { label: "News", previewKey: "query" },
  get_user_profile: { label: "Profile" },
  update_risk_score: { label: "Update Risk", previewKey: "score" },
  query_memory: { label: "Memory", previewKey: "text" },
};

function previewFor(c: Citation): string | null {
  const meta = TOOL_META[c.tool];
  if (!meta?.previewKey) return null;
  const v = (c.args as Record<string, unknown>)?.[meta.previewKey];
  if (v == null) return null;
  const s = String(v);
  return s.length > 24 ? s.slice(0, 22) + "…" : s;
}



function fmtNum(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Math.abs(n) >= 1) return n.toFixed(2);
  return String(n);
}

function formatValue(v: unknown, depth = 0): string {
  if (v == null) return "—";
  if (typeof v === "number") return fmtNum(v);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (v.length === 0) return "[]";
    if (depth > 0) return `${v.length} items`;
    return v
      .slice(0, 8)
      .map((x) => formatValue(x, depth + 1))
      .join(", ") + (v.length > 8 ? `, +${v.length - 8} more` : "");
  }
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .slice(0, 4)
      .map(([k, val]) => `${k}: ${formatValue(val, depth + 1)}`)
      .join(" · ");
  }
  return String(v);
}

function ResultView({ result, tool }: { result: string; tool: string }) {
  const parsed = parseToolResult(result);

  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const obj = parsed as Record<string, unknown>;
    if (Array.isArray(obj.top_trending)) {
      return <HotTrendsResult scanTime={obj.scan_time} trends={obj.top_trending} />;
    }
  }

  // News-style: array of articles → render headline list.
  if (Array.isArray(parsed) && parsed.length > 0 && typeof parsed[0] === "object") {
    return (
      <ul className="space-y-1.5">
        {(parsed as Record<string, unknown>[]).slice(0, 8).map((item, i) => {
          const title = (item.title || item.headline || item.name || item.symbol || item.ticker) as
            | string
            | undefined;
          const url = (item.url || item.link) as string | undefined;
          const meta: string[] = [];
          if (item.source) meta.push(String(item.source));
          if (item.published_at) meta.push(String(item.published_at).slice(0, 10));
          if (item.sentiment) meta.push(String(item.sentiment));
          const summary = (item.summary || item.description) as string | undefined;
          return (
            <li key={i} className="rounded border border-line bg-surface p-2">
              {title && (url
                ? <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-[11px] text-content hover:text-accent hover:underline underline-offset-2"
                  >
                    {title}
                  </a>
                : <p className="font-medium text-[11px] text-content">{title}</p>
              )}
              {meta.length > 0 && (
                <p className="mt-0.5 text-[10px] text-content-muted">
                  {meta.join(" · ")}
                </p>
              )}
              {!title && !summary && (
                <p className="text-[10px] text-content-muted">{formatValue(item)}</p>
              )}
              {summary && (
                <p className="mt-1 text-[10px] text-content-muted line-clamp-3">
                  {summary}
                </p>
              )}
            </li>
          );
        })}
        {parsed.length > 8 && (
          <li className="text-[10px] text-content-muted">
            +{parsed.length - 8} more
          </li>
        )}
      </ul>
    );
  }

  // Object → render as key/value grid.
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const entries = Object.entries(parsed as Record<string, unknown>);
    return (
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {entries.slice(0, 24).map(([k, v]) => (
          <div key={k} className="contents">
            <span className="text-overline uppercase text-content-muted">
              {k.replace(/_/g, " ")}
            </span>
            <span className="text-[10px] text-content break-words">
              {formatValue(v)}
            </span>
          </div>
        ))}
        {entries.length > 24 && (
          <span className="col-span-2 text-[10px] text-content-muted">
            +{entries.length - 24} more fields
          </span>
        )}
      </div>
    );
  }

  // Fallback: plain text.
  void tool;
  return (
    <p className="whitespace-pre-wrap break-words text-[10px] text-content">
      {result}
    </p>
  );
}

function HotTrendsResult({ scanTime, trends }: { scanTime: unknown; trends: unknown[] }) {
  const items = trends.filter(isRecord).slice(0, 8);

  return (
    <div className="space-y-2">
      {typeof scanTime === "string" && (
        <p className="text-[10px] text-content-muted">
          Scan time: <span className="text-content">{scanTime}</span>
        </p>
      )}
      <div className="space-y-1.5">
        {items.map((item, i) => {
          const symbol = String(item.symbol ?? item.ticker ?? `#${i + 1}`);
          const mentions = item.mentions;
          const sources = Array.isArray(item.sources) ? item.sources.map(String) : [];
          const signals = Array.isArray(item.signals) ? item.signals.map(String) : [];

          return (
            <div key={`${symbol}-${i}`} className="rounded border border-line bg-surface p-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] font-semibold text-accent">{symbol}</span>
                {mentions !== undefined && (
                  <span className="text-[10px] text-content-muted">
                    {String(mentions)} mentions
                  </span>
                )}
              </div>
              {signals.length > 0 && (
                <p className="mt-1 text-[10px] text-content">
                  {signals.slice(0, 3).join(" · ")}
                </p>
              )}
              {sources.length > 0 && (
                <p className="mt-0.5 text-[10px] text-content-muted">
                  {sources.slice(0, 3).join(" · ")}
                </p>
              )}
            </div>
          );
        })}
      </div>
      {trends.length > items.length && (
        <p className="text-[10px] text-content-muted">
          +{trends.length - items.length} more
        </p>
      )}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const meta = TOOL_META[citation.tool] ?? { label: citation.tool };
  const preview = previewFor(citation);
  const hasResult = !!citation.result;

  return (
    <div className="inline-flex flex-col">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1 rounded-md border border-line bg-surface-raised px-2 py-0.5 text-[10px] text-content-muted transition",
          "hover:border-accent hover:text-accent",
          open && "border-accent text-accent"
        )}
      >
        <Database className="h-2.5 w-2.5" />
        <span className="font-medium">{meta.label}</span>
        {preview && (
          <span className="num text-content-muted/80">: {preview}</span>
        )}
        <ChevronDown
          className={cn("h-2.5 w-2.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="mt-1 max-w-md space-y-2 rounded-md border border-line bg-surface-raised p-2">
          {hasResult ? (
            <>
              <div className="flex items-center justify-between">
                <span className="inline-flex items-center gap-1 text-overline uppercase text-content-muted">
                  <Sparkles className="h-2.5 w-2.5 text-accent" />
                  Result
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowRaw((v) => !v);
                  }}
                  className="text-overline uppercase text-content-muted hover:text-accent"
                >
                  {showRaw ? "pretty" : "raw"}
                </button>
              </div>
              {showRaw ? (
                <pre className="max-h-64 overflow-auto rounded bg-surface p-1.5 font-mono text-[10px] text-content-muted whitespace-pre-wrap break-all">
                  {citation.result}
                </pre>
              ) : (
                <div className="max-h-64 overflow-auto">
                  <ResultView result={citation.result!} tool={citation.tool} />
                </div>
              )}
              <details className="text-[10px] text-content-muted">
                <summary className="cursor-pointer uppercase tracking-widest hover:text-accent">
                  <Code2 className="mr-1 inline h-2.5 w-2.5" />
                  Call
                </summary>
                <pre className="mt-1 overflow-x-auto rounded bg-surface p-1.5 font-mono text-[10px]">
                  {citation.tool}({JSON.stringify(citation.args, null, 2)})
                </pre>
              </details>
            </>
          ) : (
            <pre className="overflow-x-auto font-mono text-[10px] text-content-muted">
              <Code2 className="mr-1 inline h-2.5 w-2.5" />
              {citation.tool}({JSON.stringify(citation.args, null, 2).slice(0, 400)})
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
