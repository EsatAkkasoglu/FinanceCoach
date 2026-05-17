import { useEffect, useState } from "react";
import {
  Plus, Briefcase, Pencil, Trash2, Loader2, Sparkles, Activity,
} from "lucide-react";
import { toast } from "sonner";

import { listPortfolio, deleteHolding, type Holding, type PortfolioTotals } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useDashboardStore } from "@/store";
import { useFxRates, type UseFxRates } from "@/lib/fx";
import { Button } from "@/components/ui/Button";
import { HoldingFormModal } from "./HoldingFormModal";
import { TickerDrawer } from "@/components/insights/TickerDrawer";
import { Disclaimer } from "@/components/ui/Disclaimer";

const ASSET_BADGE: Record<string, string> = {
  stock: "bg-gain/15 text-gain",
  etf: "bg-gain/10 text-gain",
  crypto: "bg-warning/15 text-warning",
  bond: "bg-accent/15 text-accent",
  cash: "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))]",
};

export function Portfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [totals, setTotals] = useState<PortfolioTotals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<Holding | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [analysisTicker, setAnalysisTicker] = useState<string | null>(null);

  const invalidateDashboard = useDashboardStore((s) => s.invalidate);
  const fx = useFxRates();

  async function load(silent = false) {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const r = await listPortfolio();
      setHoldings(r.holdings);
      setTotals(r.totals);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  function refresh() {
    invalidateDashboard();
    void load(true);
  }

  async function handleDelete(h: Holding) {
    if (h.id == null) return;
    if (!window.confirm(`Remove ${h.ticker} from your portfolio?`)) return;
    setDeletingId(h.id);
    // Optimistic update
    const prev = holdings;
    setHoldings(holdings.filter((x) => x.id !== h.id));
    try {
      await deleteHolding(h.id);
      toast.success(`${h.ticker} removed`);
      refresh();
    } catch (err) {
      setHoldings(prev);
      toast.error(`Couldn't remove: ${(err as Error).message}`);
    } finally {
      setDeletingId(null);
    }
  }

  const isEmpty = !loading && holdings.length === 0;

  return (
    <div>
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Portfolio</h1>
          <p className="text-sm text-[hsl(var(--text-muted))]">
            Everything you own, all in one place.
          </p>
        </div>
        {!isEmpty && (
          <Button onClick={() => setAddOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> Add holding
          </Button>
        )}
      </header>

      {error && (
        <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      {loading ? (
        <PortfolioSkeleton />
      ) : isEmpty ? (
        <EmptyPortfolio onAdd={() => setAddOpen(true)} />
      ) : (
        <>
          <SummaryRow totals={totals} count={holdings.length} holdings={holdings} fx={fx} />
          <HoldingsTable
            holdings={holdings}
            deletingId={deletingId}
            fx={fx}
            onEdit={setEditing}
            onDelete={handleDelete}
            onAnalyze={setAnalysisTicker}
          />
        </>
      )}

      <HoldingFormModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSaved={refresh}
      />
      <HoldingFormModal
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSaved={refresh}
        editing={editing}
      />
      <TickerDrawer ticker={analysisTicker} onClose={() => setAnalysisTicker(null)} />
      <Disclaimer className="mt-8 text-center" />
    </div>
  );
}

// ── Summary row ─────────────────────────────────────────────────────────────

function SummaryRow({
  totals, count, holdings, fx,
}: {
  totals: PortfolioTotals | null;
  count: number;
  holdings: Holding[];
  fx: UseFxRates;
}) {
  if (!totals) return null;

  // If FX rates are loaded, recompute totals in the display currency by
  // converting each holding individually. Otherwise fall back to the backend
  // totals (which silently assumes a single currency).
  let value = totals.value;
  let pnl = totals.pnl;
  let pnlPct = totals.pnl_pct;
  let displayCcy = "USD";
  if (fx.rates) {
    displayCcy = fx.target;
    let v = 0, c = 0;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.convert(h.current_value ?? 0, ccy);
      const hc = fx.convert(h.cost_total ?? (h.cost_basis * h.quantity), ccy);
      if (hv != null) v += hv;
      if (hc != null) c += hc;
    }
    value = v;
    pnl = v - c;
    pnlPct = c > 0 ? (pnl / c) * 100 : 0;
  }

  const positive = pnl >= 0;
  return (
    <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
      <div className="card">
        <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Net worth</div>
        <div className="num mt-2 text-2xl font-semibold">{formatCurrency(value, displayCcy)}</div>
      </div>
      <div className="card">
        <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">All-time P&L</div>
        <div className={cn("num mt-2 text-2xl font-semibold", positive ? "text-gain" : "text-loss")}>
          {formatPercent(pnlPct)}
        </div>
        <div className={cn("mt-1 text-xs", positive ? "text-gain" : "text-loss")}>
          {formatCurrency(pnl, displayCcy)}
        </div>
      </div>
      <div className="card">
        <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Positions</div>
        <div className="num mt-2 text-2xl font-semibold">{count}</div>
      </div>
    </div>
  );
}

// ── Holdings table ──────────────────────────────────────────────────────────

function HoldingsTable({
  holdings, deletingId, fx, onEdit, onDelete, onAnalyze,
}: {
  holdings: Holding[];
  deletingId: number | null;
  fx: UseFxRates;
  onEdit: (h: Holding) => void;
  onDelete: (h: Holding) => void;
  onAnalyze: (ticker: string) => void;
}) {
  // Convert a per-holding figure to the display currency, falling back to
  // formatting in the holding's native currency when rates aren't ready.
  function fmt(v: number, h: Holding) {
    const native = h.currency ?? "USD";
    if (!fx.rates) return formatCurrency(v, native);
    const conv = fx.convert(v, native);
    return conv == null ? formatCurrency(v, native) : formatCurrency(conv, fx.target);
  }
  return (
    <div className="card overflow-hidden p-0">
      <table className="num min-w-full text-sm">
        <thead className="text-xs text-[hsl(var(--text-muted))]">
          <tr className="border-b border-[hsl(var(--border))]">
            <th className="px-4 py-3 text-left font-normal">Ticker</th>
            <th className="px-3 py-3 text-left font-normal">Type</th>
            <th className="px-3 py-3 text-right font-normal">Qty</th>
            <th className="px-3 py-3 text-right font-normal">Cost</th>
            <th className="px-3 py-3 text-right font-normal">Price</th>
            <th className="px-3 py-3 text-right font-normal">Value</th>
            <th className="px-3 py-3 text-right font-normal">P&L</th>
            <th className="px-2 py-3 w-20"></th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr
              key={h.id ?? h.ticker}
              className={cn(
                "group border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--surface-2))]/50 transition",
                deletingId === h.id && "opacity-40 pointer-events-none",
              )}
            >
              <td className="px-4 py-3 font-semibold">{h.ticker}</td>
              <td className="px-3 py-3">
                <span className={cn("rounded px-1.5 py-0.5 text-[10px] uppercase", ASSET_BADGE[h.asset_class])}>
                  {h.asset_class}
                </span>
              </td>
              <td className="px-3 py-3 text-right">{h.quantity}</td>
              <td className="px-3 py-3 text-right text-[hsl(var(--text-muted))]">
                {fmt(h.cost_basis, h)}
              </td>
              <td className="px-3 py-3 text-right">
                {fmt(h.current_price ?? h.cost_basis, h)}
              </td>
              <td className="px-3 py-3 text-right font-medium">
                {fmt(h.current_value ?? 0, h)}
              </td>
              <td className={cn(
                "px-3 py-3 text-right",
                (h.pnl ?? 0) >= 0 ? "text-gain" : "text-loss",
              )}>
                {formatPercent(h.pnl_pct ?? 0)}
              </td>
              <td className="px-2 py-3">
                <div className="flex items-center justify-end gap-0.5">
                  {(h.asset_class === "stock" || h.asset_class === "etf") && (
                    <button
                      onClick={() => onAnalyze(h.ticker)}
                      className="rounded p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface))] hover:text-accent"
                      title={`8-dim analysis for ${h.ticker}`}
                      aria-label={`Analyze ${h.ticker}`}
                    >
                      <Activity className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <div className="flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                    <button
                      onClick={() => onEdit(h)}
                      className="rounded p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface))] hover:text-accent"
                      aria-label={`Edit ${h.ticker}`}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => onDelete(h)}
                      className="rounded p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface))] hover:text-loss"
                      aria-label={`Delete ${h.ticker}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Empty / loading ─────────────────────────────────────────────────────────

function EmptyPortfolio({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="card flex flex-col items-center text-center py-12">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent-muted">
        <Briefcase className="h-6 w-6 text-accent" />
      </div>
      <h2 className="text-lg font-semibold tracking-tight">Add your investments</h2>
      <p className="mt-1 max-w-md text-sm text-[hsl(var(--text-muted))]">
        Track stocks, ETFs, crypto, and bonds in one place. To import from a broker
        statement, head to <span className="font-medium text-accent">Budget</span> — the AI
        figures out where each row belongs.
      </p>

      <div className="mt-6 grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
        <CTACard
          icon={<Plus className="h-5 w-5" />}
          title="Add manually"
          description="Enter your positions one by one — quick and precise."
          accent
          onClick={onAdd}
        />
        <CTACard
          icon={<Sparkles className="h-5 w-5" />}
          title="Ask the coach"
          description="Describe your holdings in chat — the assistant logs them for you."
          onClick={() => toast.info("Open New chat from the sidebar to get started.")}
        />
      </div>
    </div>
  );
}

function CTACard({
  icon, title, description, onClick, accent = false,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  onClick: () => void;
  accent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition",
        accent
          ? "border-accent bg-accent-muted/30 hover:bg-accent-muted/50"
          : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
      )}
    >
      <span className={cn(
        "flex h-9 w-9 items-center justify-center rounded-lg",
        accent ? "bg-accent text-white" : "bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]",
      )}>
        {icon}
      </span>
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-xs text-[hsl(var(--text-muted))]">{description}</span>
    </button>
  );
}

function PortfolioSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card h-24 animate-pulse">
            <div className="h-3 w-20 rounded bg-[hsl(var(--surface-2))]" />
            <div className="mt-3 h-7 w-32 rounded bg-[hsl(var(--surface-2))]" />
          </div>
        ))}
      </div>
      <div className="card flex h-32 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
      </div>
    </div>
  );
}
