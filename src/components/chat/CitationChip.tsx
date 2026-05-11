import { useState } from "react";
import { Code2, Database, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Citation } from "@/store";

/**
 * Maps backend tool names to a human label + a quick "preview" string built
 * from the most-relevant arg, so the chip is informative at a glance:
 *   get_quote(ticker="GLD") → "GLD"
 *   search_fund(query="altın") → "altın"
 *   analyze_ticker_8dim(ticker="NVDA", fast=true) → "NVDA"
 */
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

export function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[citation.tool] ?? { label: citation.tool };
  const preview = previewFor(citation);

  return (
    <div className="inline-flex flex-col">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-0.5 text-[10px] text-[hsl(var(--text-muted))] transition",
          "hover:border-accent hover:text-accent",
          open && "border-accent text-accent"
        )}
      >
        <Database className="h-2.5 w-2.5" />
        <span className="font-medium">{meta.label}</span>
        {preview && (
          <span className="num text-[hsl(var(--text-muted))]/80">: {preview}</span>
        )}
        <ChevronDown
          className={cn("h-2.5 w-2.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <pre className="mt-1 max-w-md overflow-x-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-2 font-mono text-[10px] text-[hsl(var(--text-muted))]">
          <Code2 className="mr-1 inline h-2.5 w-2.5" />
          {citation.tool}({JSON.stringify(citation.args, null, 2).slice(0, 400)})
        </pre>
      )}
    </div>
  );
}
