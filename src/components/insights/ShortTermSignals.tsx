/**
 * ShortTermSignals — the 4-hour crypto trade desk.
 *
 * Surfaces the backend signal engine (/crypto/targets): one risk-defined card
 * per basket coin (BTC/ETH/SOL) fusing intraday technicals + perpetual
 * derivatives + news sentiment into a directional call with an ATR-based entry,
 * profit target and stop, re-priced live. This is the "maximum profit in 4
 * hours" surface a juror scores.
 *
 * Motion is intentionally light (no WebGL) — gated on reduced-motion, never on
 * the critical path. Numbers come pre-formatted from the API; the UI never does
 * the finance math.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  TrendingUp, TrendingDown, Minus, RefreshCw, Loader2,
  Target as TargetIcon, ShieldAlert, Clock, ExternalLink, Check, X,
} from "lucide-react";
import {
  listCryptoTargets, scanCryptoTargets, listPendingTargets, confirmTarget, rejectTarget,
  horizonBucket, type TradeTarget, type TradeTargetsResponse,
} from "@/lib/api";
import { cn } from "@/lib/cn";

function fmtPrice(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

const DIR_META = {
  long: { icon: TrendingUp, cls: "text-emerald-400", bg: "bg-emerald-500/10", ring: "border-emerald-500/40", bar: "bg-emerald-500" },
  short: { icon: TrendingDown, cls: "text-red-400", bg: "bg-red-500/10", ring: "border-red-500/40", bar: "bg-red-500" },
  neutral: { icon: Minus, cls: "text-content-muted", bg: "bg-surface-raised", ring: "border-border", bar: "bg-content-muted" },
} as const;

const STATUS_CLS: Record<string, string> = {
  active: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  hit: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  stopped: "bg-red-500/15 text-red-300 border-red-500/40",
  expired: "bg-surface-raised text-content-muted border-border",
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  rejected: "bg-surface-raised text-content-muted border-border",
};

/** Asset-class i18n keys are a known closed set; fall back to "other". */
function assetClassKey(c: string | null | undefined) {
  return (["stock", "etf", "crypto", "fund"].includes(c ?? "") ? c : "other") as
    "stock" | "etf" | "crypto" | "fund" | "other";
}

function SignalCard({
  t: target, onApprove, onReject, busy,
}: {
  t: TradeTarget;
  onApprove?: (id: number) => void;
  onReject?: (id: number) => void;
  busy?: boolean;
}) {
  const { t } = useTranslation("discover");
  const [open, setOpen] = useState(false);
  const isPending = target.status === "pending";
  const bucket = horizonBucket(target.horizon_hours);
  const dir = DIR_META[target.direction] ?? DIR_META.neutral;
  const Icon = dir.icon;
  const progressPct = target.progress != null ? Math.max(0, Math.min(100, target.progress * 100)) : 0;
  const pnlPositive = (target.pnl_pct ?? 0) >= 0;

  // Rationale is built HERE from structured fields + i18n (not the backend's
  // English prose) so it localises to any language, not just en/tr.
  const tPct = target.target_price != null && target.entry_price
    ? (target.target_price / target.entry_price - 1) * 100 : null;
  const rr = target.target_price != null && target.stop_price != null && target.entry_price
    && target.entry_price !== target.stop_price
    ? Math.abs(target.target_price - target.entry_price) / Math.abs(target.entry_price - target.stop_price)
    : null;
  const thesisLine = t("shortTerm.thesisLine", {
    dir: t(`shortTerm.dir.${target.direction}`),
    conf: Math.round(target.confidence * 100),
    score: target.score.toFixed(2),
    entry: fmtPrice(target.entry_price),
    target: fmtPrice(target.target_price),
    targetPct: tPct != null ? tPct.toFixed(2) : "—",
    stop: fmtPrice(target.stop_price),
    rr: rr != null ? rr.toFixed(1) : "—",
  });

  return (
    <div className={cn("card flex flex-col gap-3 border", dir.ring)}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("inline-flex h-7 w-7 items-center justify-center rounded-full", dir.bg)}>
              <Icon className={cn("h-4 w-4", dir.cls)} />
            </span>
            <span className="truncate text-base font-semibold">{target.ticker}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className={cn("text-xs font-bold uppercase tracking-wide", dir.cls)}>
              {t(`shortTerm.dir.${target.direction}`)}
            </span>
            <span className="text-[11px] text-content-muted">
              · {t("shortTerm.confidence")} {Math.round(target.confidence * 100)}%
            </span>
            <span className="rounded-full bg-surface-raised px-1.5 py-0.5 text-[10px] text-content-muted">
              {t(`shortTerm.horizon.${bucket}`)}
            </span>
            <span className="rounded-full bg-surface-raised px-1.5 py-0.5 text-[10px] text-content-muted">
              {t(`assetClass.${assetClassKey(target.asset_class)}`)}
            </span>
          </div>
        </div>
        <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase", STATUS_CLS[target.status])}>
          {t(`shortTerm.status.${target.status}`)}
        </span>
      </div>

      {/* Price ladder */}
      <div className="grid grid-cols-4 gap-1 text-center">
        {([
          { k: "entry", v: fmtPrice(target.entry_price), sub: null, cls: "text-content" },
          { k: "now", v: fmtPrice(target.current_price ?? target.resolved_price), sub: fmtPct(target.pnl_pct), cls: pnlPositive ? "text-emerald-400" : "text-red-400" },
          { k: "target", v: fmtPrice(target.target_price), sub: null, cls: "text-emerald-400" },
          { k: "stop", v: fmtPrice(target.stop_price), sub: null, cls: "text-red-400" },
        ] as const).map((c) => (
          <div key={c.k} className="rounded-md bg-surface-raised px-1 py-1.5">
            <div className="text-[10px] uppercase tracking-wide text-content-muted">{t(`shortTerm.${c.k}`)}</div>
            <div className={cn("text-xs font-semibold tabular-nums", c.cls)}>{c.v}</div>
            {c.sub && <div className={cn("text-[10px] tabular-nums", c.cls)}>{c.sub}</div>}
          </div>
        ))}
      </div>

      {/* Progress to target */}
      <div>
        <div className="mb-1 flex items-center justify-between text-[10px] text-content-muted">
          <span>{t("shortTerm.progress")}</span>
          <span className="flex items-center gap-1">
            {target.minutes_left != null && target.status === "active" && (
              <><Clock className="h-3 w-3" />{t("shortTerm.minutesLeft", { m: target.minutes_left })}</>
            )}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-raised">
          <div className={cn("h-full rounded-full transition-all", dir.bar)} style={{ width: `${progressPct}%` }} />
        </div>
      </div>

      {/* Footer: thesis toggle */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between text-left text-[11px] text-content-muted hover:text-content"
      >
        <span className="flex items-center gap-2">
          <TargetIcon className="h-3 w-3" />
          {t("shortTerm.rr")} {target.score >= 0 ? "+" : ""}{target.score.toFixed(2)}
        </span>
        <span className="underline-offset-2 hover:underline">{open ? t("shortTerm.less") : t("shortTerm.why")}</span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.p
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden text-[11px] leading-relaxed text-content-muted"
          >
            {thesisLine}
          </motion.p>
        )}
      </AnimatePresence>

      {isPending && (
        <div className="flex items-center gap-2 border-t border-border pt-2">
          <button
            onClick={() => onApprove?.(target.id)}
            disabled={busy}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-60"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            {t("shortTerm.approve")}
          </button>
          <button
            onClick={() => onReject?.(target.id)}
            disabled={busy}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium text-content-muted hover:bg-surface disabled:opacity-60"
          >
            <X className="h-3.5 w-3.5" />
            {t("shortTerm.reject")}
          </button>
        </div>
      )}
    </div>
  );
}

export function ShortTermSignals() {
  const { t } = useTranslation("discover");
  const reduce = useReducedMotion();
  const [data, setData] = useState<TradeTargetsResponse | null>(null);
  const [pending, setPending] = useState<TradeTarget[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    const [res, pend] = await Promise.all([
      listCryptoTargets().catch(() => null),
      listPendingTargets().catch(() => []),
    ]);
    setData(res);
    setPending(pend);
    setLoading(false);
    return res;
  }, []);

  const approve = useCallback(async (id: number) => {
    setBusyId(id);
    await confirmTarget(id).catch(() => null);
    await load();
    setBusyId(null);
  }, [load]);

  const decline = useCallback(async (id: number) => {
    setBusyId(id);
    await rejectTarget(id).catch(() => null);
    await load();
    setBusyId(null);
  }, [load]);

  const rescan = useCallback(async () => {
    setScanning(true);
    await scanCryptoTargets().catch(() => null);
    await load();
    setScanning(false);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await load();
      // First-run / empty: kick a scan so the desk is never blank.
      if (!cancelled && res && res.targets.length === 0) {
        setScanning(true);
        await scanCryptoTargets().catch(() => null);
        if (!cancelled) await load();
        if (!cancelled) setScanning(false);
      }
    })();
    // Light auto-refresh so a trade opened from the chat coach (or a target
    // hitting/expiring) shows up here without a manual reload. Paused when the
    // tab is hidden to avoid needless polling.
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, 25000);
    return () => { cancelled = true; clearInterval(id); };
  }, [load]);

  const targets = data?.targets ?? [];
  const summary = data?.summary;

  const Wrapper = reduce ? "div" : motion.div;
  const wrapperProps = reduce
    ? {}
    : { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.3 } };

  return (
    <Wrapper {...wrapperProps} className="card border-l-4 border-l-accent">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <TargetIcon className="h-5 w-5 text-accent" />
            {t("shortTerm.title")}
          </h2>
          <p className="text-xs text-content-muted">{t("shortTerm.subtitle")}</p>
        </div>
        <div className="flex items-center gap-3">
          {summary && summary.total > 0 && (
            <div className="hidden items-center gap-3 text-xs text-content-muted sm:flex">
              <span>{t("shortTerm.activeCount", { n: summary.active })}</span>
              {summary.avg_pnl_pct != null && (
                <span className={cn("font-semibold tabular-nums", summary.avg_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {fmtPct(summary.avg_pnl_pct)}
                </span>
              )}
            </div>
          )}
          <button
            onClick={rescan}
            disabled={scanning}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium hover:bg-surface disabled:opacity-60"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {scanning ? t("shortTerm.scanning") : t("shortTerm.rescan")}
          </button>
        </div>
      </div>

      {pending.length > 0 && (
        <div className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
          <p className="mb-2 text-xs font-semibold text-amber-300">
            {t("shortTerm.pendingTitle", { n: pending.length })}
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {pending.map((p) => (
              <SignalCard
                key={p.id} t={p} onApprove={approve} onReject={decline} busy={busyId === p.id}
              />
            ))}
          </div>
        </div>
      )}

      {loading || (scanning && targets.length === 0) ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card h-44 animate-pulse bg-surface-raised" />
          ))}
        </div>
      ) : targets.length === 0 && pending.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-content-muted">
          <ShieldAlert className="h-6 w-6 opacity-50" />
          {t("shortTerm.empty")}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {targets.map((tg) => <SignalCard key={tg.id} t={tg} />)}
        </div>
      )}

      <p className="mt-3 flex items-center gap-1.5 text-[10px] text-content-muted">
        <ExternalLink className="h-3 w-3" />
        {t("shortTerm.notAdvice")}
      </p>
    </Wrapper>
  );
}
