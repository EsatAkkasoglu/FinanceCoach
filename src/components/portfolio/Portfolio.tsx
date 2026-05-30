import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Plus, Briefcase, Pencil, Trash2, Loader2, Sparkles, Activity,
} from "lucide-react";
import { toast } from "sonner";

import { listPortfolio, deleteHolding, type Holding, type PortfolioTotals } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useDashboardStore, usePortfolioStore } from "@/store";
import { useFxRates, type UseFxRates } from "@/lib/fx";
import { Button } from "@/components/ui/Button";
import { HoldingFormModal } from "./HoldingFormModal";
import { HoldingChartDrawer } from "./HoldingChartDrawer";
import { TickerDrawer } from "@/components/insights/TickerDrawer";
import { Disclaimer } from "@/components/ui/Disclaimer";

const STALE_MS = 2 * 60 * 1000;

const ASSET_BADGE: Record<string, string> = {
  stock: "bg-gain/15 text-gain",
  etf: "bg-gain/10 text-gain",
  crypto: "bg-warning/15 text-warning",
  bond: "bg-accent/15 text-accent",
  fund: "bg-[#8B5CF6]/15 text-[#8B5CF6]",
  cash: "bg-surface-raised text-content-muted",
};

export function Portfolio() {
  const { t } = useTranslation("portfolio");
  const { cache, loading, setCache, setLoading, invalidate: invalidatePortfolio } = usePortfolioStore();
  const [error, setError] = useState<string | null>(null);

  const holdings = cache?.holdings ?? [];
  const totals = cache?.totals ?? null;

  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<Holding | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [analysisTicker, setAnalysisTicker] = useState<string | null>(null);
  const [chartHolding, setChartHolding] = useState<Holding | null>(null);

  const invalidateDashboard = useDashboardStore((s) => s.invalidate);
  const fx = useFxRates();

  async function load(forceRefresh = false) {
    if (!forceRefresh && cache && Date.now() - cache.fetchedAt < STALE_MS) return;
    if (!forceRefresh && loading) return;
    setLoading(true);
    setError(null);
    try {
      const r = await listPortfolio();
      setCache({ holdings: r.holdings, totals: r.totals, fetchedAt: Date.now() });
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function refresh() {
    invalidateDashboard();
    invalidatePortfolio();
    void load(true);
  }

  async function handleDelete(h: Holding) {
    if (h.id == null) return;
    if (!window.confirm(`Remove ${h.ticker} from your portfolio?`)) return;
    setDeletingId(h.id);
    // Optimistic update in cache
    if (cache) {
      setCache({ ...cache, holdings: cache.holdings.filter((x) => x.id !== h.id) });
    }
    try {
      await deleteHolding(h.id);
      toast.success(`${h.ticker} removed`);
      refresh();
    } catch (err) {
      if (cache) setCache(cache); // restore
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
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-sm text-content-muted">
            {t("subtitle")}
          </p>
        </div>
        {!isEmpty && (
          <Button onClick={() => setAddOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> {t("addHolding")}
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
            onChart={setChartHolding}
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
      <HoldingChartDrawer
        ticker={chartHolding?.ticker ?? null}
        assetClass={chartHolding?.asset_class ?? null}
        onClose={() => setChartHolding(null)}
      />
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
  const { t } = useTranslation("portfolio");
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
    <div className="mb-6 overflow-hidden rounded-3xl border border-line bg-gradient-to-br from-surface-raised via-surface to-surface p-6 md:p-8">
      <div className="flex flex-wrap items-end justify-between gap-6">
        {/* Dominant figure */}
        <div className="min-w-0">
          <div className="text-overline uppercase text-content-muted">{t("netWorth")}</div>
          <div className="num mt-1 text-4xl font-bold tracking-tight md:text-5xl">
            {formatCurrency(value, displayCcy)}
          </div>
        </div>
        {/* Secondary stats */}
        <div className="flex items-end gap-8">
          <div>
            <div className="text-overline uppercase text-content-muted">{t("allTimePnl")}</div>
            <div className={cn("num mt-1 text-2xl font-semibold", positive ? "text-gain" : "text-loss")}>
              {formatPercent(pnlPct)}
            </div>
            <div className={cn("text-xs", positive ? "text-gain" : "text-loss")}>
              {formatCurrency(pnl, displayCcy)}
            </div>
          </div>
          <div>
            <div className="text-overline uppercase text-content-muted">{t("positions")}</div>
            <div className="num mt-1 text-2xl font-semibold">{count}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Holdings table ──────────────────────────────────────────────────────────

function HoldingsTable({
  holdings, deletingId, fx, onEdit, onDelete, onAnalyze, onChart,
}: {
  holdings: Holding[];
  deletingId: number | null;
  fx: UseFxRates;
  onEdit: (h: Holding) => void;
  onDelete: (h: Holding) => void;
  onAnalyze: (ticker: string) => void;
  onChart: (h: Holding) => void;
}) {
  const { t } = useTranslation("portfolio");
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
        <caption className="sr-only">{t("table.caption", { defaultValue: "Holdings overview" })}</caption>
        <thead className="text-xs text-content-muted">
          <tr className="border-b border-line">
            <th scope="col" className="px-4 py-3 text-left font-normal">{t("table.ticker")}</th>
            <th scope="col" className="px-3 py-3 text-left font-normal">{t("table.type")}</th>
            <th scope="col" className="px-3 py-3 text-right font-normal">{t("table.qty")}</th>
            <th scope="col" className="px-3 py-3 text-right font-normal">{t("table.cost")}</th>
            <th scope="col" className="px-3 py-3 text-right font-normal">{t("table.price")}</th>
            <th scope="col" className="px-3 py-3 text-right font-normal">{t("table.value")}</th>
            <th scope="col" className="px-3 py-3 text-right font-normal">{t("table.pnl")}</th>
            <th scope="col" className="px-2 py-3 w-20"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr
              key={h.id ?? h.ticker}
              className={cn(
                "group border-b border-line last:border-0 hover:bg-surface-raised/50 transition",
                deletingId === h.id && "opacity-40 pointer-events-none",
              )}
            >
              <td className="px-4 py-3 font-semibold">
                {h.asset_class === "cash" ? (
                  h.ticker
                ) : (
                  <button
                    type="button"
                    onClick={() => onChart(h)}
                    className="rounded text-left hover:text-accent hover:underline underline-offset-2"
                    title={t("chart.open", { defaultValue: `Price history for ${h.ticker}` })}
                    aria-label={t("chart.open", { defaultValue: `Price history for ${h.ticker}` })}
                  >
                    {h.ticker}
                  </button>
                )}
              </td>
              <td className="px-3 py-3">
                <span className={cn("rounded px-1.5 py-0.5 text-overline uppercase", ASSET_BADGE[h.asset_class])}>
                  {h.asset_class}
                </span>
              </td>
              <td className="px-3 py-3 text-right">{h.quantity}</td>
              <td className="px-3 py-3 text-right text-content-muted">
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
                      type="button"
                      onClick={() => onAnalyze(h.ticker)}
                      className="rounded p-1.5 text-content-muted hover:bg-surface hover:text-accent"
                      title={`8-dim analysis for ${h.ticker}`}
                      aria-label={`Analyze ${h.ticker}`}
                    >
                      <Activity aria-hidden="true" className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <div className="flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={() => onEdit(h)}
                      className="rounded p-1.5 text-content-muted hover:bg-surface hover:text-accent"
                      aria-label={`Edit ${h.ticker}`}
                    >
                      <Pencil aria-hidden="true" className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(h)}
                      className="rounded p-1.5 text-content-muted hover:bg-surface hover:text-loss"
                      aria-label={`Delete ${h.ticker}`}
                    >
                      <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
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
  const { t } = useTranslation("portfolio");
  return (
    <div className="card flex flex-col items-center text-center py-12">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent-muted">
        <Briefcase className="h-6 w-6 text-accent" />
      </div>
      <h2 className="text-lg font-semibold tracking-tight">{t("empty.title")}</h2>
      <p className="mt-1 max-w-md text-sm text-content-muted">
        {t("empty.desc")}
      </p>

      <div className="mt-6 grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
        <CTACard
          icon={<Plus className="h-5 w-5" />}
          title={t("empty.addManually")}
          description={t("empty.addManuallyDesc")}
          accent
          onClick={onAdd}
        />
        <CTACard
          icon={<Sparkles className="h-5 w-5" />}
          title={t("empty.askCoach")}
          description={t("empty.askCoachDesc")}
          onClick={() => toast.info(t("empty.openChat"))}
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
          : "border-line bg-surface-raised hover:border-content-muted",
      )}
    >
      <span className={cn(
        "flex h-9 w-9 items-center justify-center rounded-lg",
        accent ? "bg-accent text-white" : "bg-surface text-content-muted",
      )}>
        {icon}
      </span>
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-xs text-content-muted">{description}</span>
    </button>
  );
}

function PortfolioSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card h-24 animate-pulse">
            <div className="h-3 w-20 rounded bg-surface-raised" />
            <div className="mt-3 h-7 w-32 rounded bg-surface-raised" />
          </div>
        ))}
      </div>
      <div className="card flex h-32 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
      </div>
    </div>
  );
}
