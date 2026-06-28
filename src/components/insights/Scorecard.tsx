/**
 * Scorecard — the trade-signal "jury".
 *
 * Surfaces /eval/scorecard: a research-grounded replay of resolved trade targets
 * into per (horizon × asset-class) metrics. Win-rate is NOT the headline — the
 * discriminating numbers are risk-adjusted return (Sortino), confidence
 * calibration (Brier/ECE) and the Deflated Sharpe. Hidden until there is at
 * least one resolved trade to score.
 *
 * Motion is reduced-motion-gated; numbers come pre-computed from the API.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "framer-motion";
import { Gavel, Info } from "lucide-react";
import { getScorecard, type HorizonBucket, type ScorecardCell, type ScorecardResponse } from "@/lib/api";
import { cn } from "@/lib/cn";

function fmt(n: number | null | undefined, digits = 2, suffix = "") {
  if (n == null) return "—";
  return `${n.toFixed(digits)}${suffix}`;
}

function tone(n: number | null | undefined, good = 0) {
  if (n == null) return "text-content-muted";
  return n >= good ? "text-emerald-400" : "text-red-400";
}

/** Brier/ECE are error metrics — lower is better. */
function calibTone(n: number | null | undefined, warn: number) {
  if (n == null) return "text-content-muted";
  return n <= warn ? "text-emerald-400" : "text-amber-400";
}

function assetClassKey(c: string | null | undefined) {
  return (["stock", "etf", "crypto", "fund"].includes(c ?? "") ? c : "other") as
    "stock" | "etf" | "crypto" | "fund" | "other";
}

function Metric({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-lg bg-surface-raised px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-wide text-content-muted">{label}</div>
      <div className={cn("text-sm font-semibold tabular-nums", cls)}>{value}</div>
    </div>
  );
}

function CellRow({ c }: { c: ScorecardCell }) {
  const { t } = useTranslation("discover");
  return (
    <tr className="border-t border-border/60">
      <td className="py-1.5 pr-2">
        <span className="font-medium">{t(`shortTerm.horizon.${c.horizon as HorizonBucket}`, { defaultValue: c.horizon })}</span>
        <span className="ml-1.5 text-[10px] text-content-muted">{t(`assetClass.${assetClassKey(c.asset_class)}`)}</span>
      </td>
      <td className="py-1.5 text-center tabular-nums">{c.n_resolved}</td>
      <td className={cn("py-1.5 text-center tabular-nums", tone(c.avg_return_pct))}>{fmt(c.avg_return_pct, 2, "%")}</td>
      <td className="py-1.5 text-center tabular-nums">{c.hit_rate == null ? "—" : `${Math.round(c.hit_rate * 100)}%`}</td>
      <td className={cn("py-1.5 text-center tabular-nums", tone(c.sortino))}>{fmt(c.sortino)}</td>
      <td className={cn("py-1.5 text-center tabular-nums", tone(c.dsr, 0.5))}>{c.dsr == null ? "—" : c.dsr.toFixed(2)}</td>
      <td className={cn("py-1.5 text-center tabular-nums", calibTone(c.brier, 0.25))}>{fmt(c.brier)}</td>
    </tr>
  );
}

export function Scorecard() {
  const { t } = useTranslation("discover");
  const reduce = useReducedMotion();
  const [data, setData] = useState<ScorecardResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getScorecard()
      .then((d) => { if (!cancelled) { setData(d); setLoaded(true); } })
      .catch(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  // Hidden until there is something to judge.
  if (!loaded || !data || !data.ok || data.n_resolved === 0) return null;

  const o = data.overall;
  const Wrapper = reduce ? "div" : motion.div;
  const wrapperProps = reduce
    ? {}
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3 } };

  return (
    <Wrapper {...wrapperProps} className="card border-l-4 border-l-accent">
      <div className="mb-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Gavel className="h-5 w-5 text-accent" />
          {t("scorecard.title")}
        </h2>
        <p className="text-xs text-content-muted">
          {t("scorecard.subtitle", { n: data.n_resolved })}
        </p>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label={t("scorecard.avgReturn")} value={fmt(o.avg_return_pct, 2, "%")} cls={tone(o.avg_return_pct)} />
        <Metric label={t("scorecard.sortino")} value={fmt(o.sortino)} cls={tone(o.sortino)} />
        <Metric label={t("scorecard.dsr")} value={o.dsr == null ? "—" : o.dsr.toFixed(2)} cls={tone(o.dsr, 0.5)} />
        <Metric label={t("scorecard.maxDd")} value={fmt(o.max_drawdown_pct, 1, "%")} cls="text-red-400" />
        <Metric label={t("scorecard.brier")} value={fmt(o.brier)} cls={calibTone(o.brier, 0.25)} />
        <Metric label={t("scorecard.ece")} value={fmt(o.ece)} cls={calibTone(o.ece, 0.15)} />
      </div>

      {data.by_cell.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-content-muted">
              <tr>
                <th className="py-1 text-left font-medium">{t("scorecard.cell")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.n")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.avgReturn")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.hit")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.sortino")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.dsr")}</th>
                <th className="py-1 text-center font-medium">{t("scorecard.brier")}</th>
              </tr>
            </thead>
            <tbody>
              {data.by_cell.map((c) => <CellRow key={`${c.horizon}-${c.asset_class}`} c={c} />)}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 flex items-start gap-1.5 text-[10px] leading-relaxed text-content-muted">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        {t("scorecard.notes")}
      </p>
    </Wrapper>
  );
}
