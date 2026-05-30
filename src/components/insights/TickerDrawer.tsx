/**
 * TickerDrawer — slide-in detail panel for a ticker (stock, ETF, or crypto).
 *
 * UX improvements over v1:
 * - Progressive loading: each section fetches independently and appears as ready
 * - Dimension strength labels (Strong / Moderate / Weak) per bar row
 * - Plain-language dimension descriptions (info icon tooltip)
 * - Expandable dimension rows — click to see the raw detail values
 * - RSI interpreted as a plain range label, not just a number
 * - Crypto: shows Fear & Greed value, market cap, rank in header
 * - Recommendation includes signal count and disclaimer
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, ExternalLink, ChevronDown, ChevronUp, Info } from "lucide-react";
import {
  analyzeEightDim, getTechnicals, getDividend, searchNews,
  type EightDimResult, type TechnicalsResult, type DividendResult, type NewsArticle,
} from "@/lib/api";
import { cn } from "@/lib/cn";

interface Props {
  ticker: string | null;
  onClose: () => void;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function scoreStrength(score: number): "strong" | "moderate" | "weak" {
  if (score >= 0.67) return "strong";
  if (score >= 0.40) return "moderate";
  return "weak";
}

function rsiRangeKey(rsi: number): string {
  if (rsi >= 70) return "overbought";
  if (rsi >= 60) return "overbought_zone";
  if (rsi >= 40) return "neutral";
  if (rsi >= 30) return "oversold_zone";
  return "oversold";
}

function fmtLargeUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
}

// ── main component ────────────────────────────────────────────────────────────

export function TickerDrawer({ ticker, onClose }: Props) {
  const { t } = useTranslation("discover");

  // Each section has its own loading state for progressive reveal
  const [eight, setEight] = useState<EightDimResult | null>(null);
  const [tech, setTech] = useState<TechnicalsResult | null>(null);
  const [dividend, setDividend] = useState<DividendResult | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loadingEight, setLoadingEight] = useState(false);
  const [loadingTech, setLoadingTech] = useState(false);
  const [loadingNews, setLoadingNews] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;

    setEight(null); setTech(null); setDividend(null); setNews([]);
    setLoadingEight(true); setLoadingTech(true); setLoadingNews(true);

    // Fetch in two waves: 8-dim first (slowest), tech + news in parallel
    analyzeEightDim(ticker, true)
      .catch(() => null)
      .then((e) => { if (!cancelled) { setEight(e); setLoadingEight(false); } });

    Promise.all([
      getTechnicals(ticker).catch(() => null),
      getDividend(ticker).catch(() => null),
    ]).then(([tc, dv]) => {
      if (!cancelled) { setTech(tc); setDividend(dv); setLoadingTech(false); }
    });

    searchNews(ticker, 4)
      .catch(() => [])
      .then((n) => { if (!cancelled) { setNews(n); setLoadingNews(false); } });

    return () => { cancelled = true; };
  }, [ticker]);

  if (!ticker) return null;

  const isCrypto = eight?.asset_class === "crypto";

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-bg p-5 shadow-2xl animate-in slide-in-from-right">

        {/* Header */}
        <header className="mb-5 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-overline uppercase text-content-muted">
              {t("drawer.tickerAnalysis")}
            </p>
            <h2 className="font-mono text-3xl font-semibold text-emerald-300 leading-tight">
              {ticker}
            </h2>
            {eight?.name && isCrypto && (
              <p className="text-sm text-content-muted mt-0.5">{eight.name}</p>
            )}

            {/* Crypto market data strip */}
            {eight?.market_data && isCrypto && (
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                {eight.market_data.price_usd != null && (
                  <span className="num text-base font-semibold">
                    ${eight.market_data.price_usd.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                  </span>
                )}
                {eight.market_data.change_pct_24h != null && (
                  <span className={cn(
                    "text-sm font-medium",
                    eight.market_data.change_pct_24h >= 0 ? "text-gain" : "text-loss"
                  )}>
                    {eight.market_data.change_pct_24h >= 0 ? "+" : ""}
                    {eight.market_data.change_pct_24h.toFixed(2)}%
                  </span>
                )}
                <span className="text-xs text-content-muted">
                  {fmtLargeUsd(eight.market_data.market_cap_usd)} mkt cap
                </span>
                {eight.market_data.rank != null && (
                  <span className="text-xs text-content-muted">
                    {t("drawer.cryptoRank", { rank: eight.market_data.rank })}
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-2 text-content-muted hover:bg-surface-raised hover:text-content"
            aria-label={t("drawer.close")}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* 8-dim section — progressive */}
        {loadingEight
          ? <SectionSkeleton title={t("drawer.eightDimTitle")} />
          : eight && <EightDimSection result={eight} />}

        {/* Technicals section — progressive */}
        {loadingTech
          ? <SectionSkeleton title={t("drawer.technicalsTitle")} />
          : tech && <TechnicalsSection result={tech} />}

        {/* Dividend — only for non-crypto, no skeleton (optional data) */}
        {!loadingTech && dividend && !isCrypto && <DividendSection result={dividend} />}

        {/* News — progressive */}
        {loadingNews
          ? <SectionSkeleton title={t("drawer.newsTitle")} />
          : news.length > 0 && <NewsSection articles={news} />}
      </aside>
    </div>
  );
}

// ── Section skeleton ──────────────────────────────────────────────────────────

function SectionSkeleton({ title }: { title: string }) {
  return (
    <section className="card mb-3 animate-pulse">
      <h3 className="text-sm font-semibold text-content-muted">{title}</h3>
      <div className="mt-3 space-y-2">
        <div className="h-2 w-full rounded bg-surface-raised" />
        <div className="h-2 w-4/5 rounded bg-surface-raised" />
        <div className="h-2 w-3/5 rounded bg-surface-raised" />
      </div>
    </section>
  );
}

// ── 8-dim section ─────────────────────────────────────────────────────────────

function EightDimSection({ result }: { result: EightDimResult }) {
  const { t } = useTranslation("discover");
  const [expanded, setExpanded] = useState<string | null>(null);

  if (result.error && !result.dimensions) {
    return (
      <section className="card mb-3">
        <h3 className="text-sm font-semibold">{t("drawer.eightDimTitle")}</h3>
        <p className="mt-2 text-xs text-warning">{result.error}</p>
      </section>
    );
  }

  const dims = Object.entries(result.dimensions ?? {}).map(([key, val]) => ({
    key,
    score: typeof val.score === "number" ? val.score : 0,
    detail: val,
  }));

  const rec = result.recommendation ?? "—";
  const recTone =
    rec === "BUY" ? "text-gain"
    : rec === "SELL" ? "text-loss"
    : "text-content-muted";

  const signalCount = dims.filter(d => !result.unavailable_dimensions?.includes(d.key)).length;

  return (
    <section className="card mb-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{t("drawer.eightDimTitle")}</h3>
          {result.final_score != null && (
            <p className="text-[10px] text-content-muted mt-0.5">
              {t("drawer.score", { value: (result.final_score * 100).toFixed(0) })}
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className={cn("text-xl font-bold", recTone)}>{rec}</p>
          <p className="text-[10px] text-content-muted leading-tight">
            {t("drawer.recommendationBasis", { count: signalCount })}
          </p>
          <p className="text-[10px] text-content-muted">{t("drawer.notAdvice")}</p>
        </div>
      </div>

      {result.degraded && (
        <p className="mt-2 text-xs text-warning">{t("drawer.eightDimDegraded")}</p>
      )}

      {/* Dimension rows */}
      <ul className="mt-4 space-y-0.5">
        {dims.map((d) => {
          const strength = scoreStrength(d.score);
          const isExpanded = expanded === d.key;
          const isUnavailable = result.unavailable_dimensions?.includes(d.key);
          const desc = t(`drawer.dimensionDesc.${d.key}`, { defaultValue: "" });

          return (
            <li key={d.key}>
              <button
                className="w-full text-left rounded-md px-2 py-1.5 hover:bg-surface-raised transition-colors"
                onClick={() => setExpanded(isExpanded ? null : d.key)}
                aria-expanded={isExpanded}
              >
                <div className="flex items-center gap-2 text-xs">
                  {/* Label */}
                  <span className="w-28 shrink-0 text-overline uppercase text-content-muted">
                    {t(`drawer.dimensions.${d.key}`, { defaultValue: d.key.replace(/_/g, " ") })}
                  </span>

                  {/* Bar */}
                  <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-surface-raised">
                    {!isUnavailable && (
                      <div
                        className={cn(
                          "h-full transition-all duration-500",
                          strength === "strong" ? "bg-gain"
                          : strength === "moderate" ? "bg-accent"
                          : "bg-loss",
                        )}
                        style={{ width: `${Math.max(2, d.score * 100)}%` }}
                      />
                    )}
                  </div>

                  {/* Strength badge */}
                  {!isUnavailable ? (
                    <span className={cn(
                      "shrink-0 rounded px-1 py-0.5 text-overline uppercase",
                      strength === "strong" ? "bg-gain/10 text-gain"
                      : strength === "moderate" ? "bg-accent/10 text-accent"
                      : "bg-loss/10 text-loss",
                    )}>
                      {t(`drawer.scoreStrength.${strength}`)}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[10px] text-content-muted">—</span>
                  )}

                  {/* Expand chevron */}
                  {isExpanded
                    ? <ChevronUp className="h-3 w-3 shrink-0 text-content-muted" />
                    : <ChevronDown className="h-3 w-3 shrink-0 text-content-muted opacity-40" />}
                </div>
              </button>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="mx-2 mb-1 rounded-md bg-surface-raised px-3 py-2 text-[11px] text-content-muted space-y-1">
                  {desc && (
                    <p className="flex gap-1.5 items-start">
                      <Info className="mt-0.5 h-3 w-3 shrink-0 text-accent" />
                      {desc}
                    </p>
                  )}
                  <DimensionDetail dimKey={d.key} detail={d.detail} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── Dimension detail (raw values shown on expand) ─────────────────────────────

function DimensionDetail({ dimKey, detail }: { dimKey: string; detail: Record<string, unknown> }) {
  const skip = new Set(["score", "source", "unavailable", "note", "error"]);

  // Custom formatters for specific dimension keys
  const formatted: [string, string][] = [];

  if (dimKey === "sentiment" && detail.fear_greed_index != null) {
    formatted.push(["Fear & Greed", `${detail.fear_greed_index} / ${detail.label ?? ""}`]);
  }
  if (dimKey === "momentum") {
    if (detail.rsi != null) formatted.push(["RSI", String((detail.rsi as number).toFixed(1))]);
    if (detail.price_vs_sma_pct != null) formatted.push(["vs SMA50", `${(detail.price_vs_sma_pct as number) >= 0 ? "+" : ""}${(detail.price_vs_sma_pct as number).toFixed(1)}%`]);
  }
  if (dimKey === "historical") {
    if (detail.year_return_pct != null) formatted.push(["1Y return", `${(detail.year_return_pct as number) >= 0 ? "+" : ""}${(detail.year_return_pct as number).toFixed(1)}%`]);
    if (detail.range_position_pct != null) formatted.push(["52W position", `${(detail.range_position_pct as number).toFixed(0)}%`]);
    if (detail.year_high != null && detail.year_low != null) {
      formatted.push(["52W range", `${detail.year_low} – ${detail.year_high}`]);
    }
  }
  if (dimKey === "relative_strength" && detail.alpha_vs_btc_pct != null) {
    formatted.push(["Alpha vs BTC (30d)", `${(detail.alpha_vs_btc_pct as number) >= 0 ? "+" : ""}${(detail.alpha_vs_btc_pct as number).toFixed(1)}%`]);
    if (detail.coin_30d_return_pct != null) formatted.push(["Coin 30d", `${(detail.coin_30d_return_pct as number).toFixed(1)}%`]);
    if (detail.btc_30d_return_pct != null) formatted.push(["BTC 30d", `${(detail.btc_30d_return_pct as number).toFixed(1)}%`]);
  }
  if (dimKey === "liquidity" && detail.vol_to_cap_ratio != null) {
    formatted.push(["Vol/Cap ratio", `${((detail.vol_to_cap_ratio as number) * 100).toFixed(1)}%`]);
  }
  if (dimKey === "market_context") {
    if (detail.vix != null) formatted.push(["VIX", String(detail.vix)]);
    if (detail.regime != null) formatted.push(["Regime", String(detail.regime)]);
    if (detail.btc_dominance_pct != null) formatted.push(["BTC dominance", `${detail.btc_dominance_pct}%`]);
    if (detail.market_cap_change_24h_pct != null) formatted.push(["Global mkt 24h", `${(detail.market_cap_change_24h_pct as number) >= 0 ? "+" : ""}${(detail.market_cap_change_24h_pct as number).toFixed(2)}%`]);
  }
  if (dimKey === "analyst_sentiment") {
    if (detail.total_analysts != null) formatted.push(["Analysts", String(detail.total_analysts)]);
    if (detail.strong_buy != null || detail.buy != null) {
      const buy = ((detail.strong_buy as number) || 0) + ((detail.buy as number) || 0);
      formatted.push(["Buy / Hold / Sell", `${buy} / ${detail.hold ?? 0} / ${((detail.sell as number) || 0) + ((detail.strong_sell as number) || 0)}`]);
    }
    if (detail.target_price != null) formatted.push(["Target price", `$${detail.target_price}`]);
  }
  if (dimKey === "fundamentals") {
    if (detail.pe_ratio != null) formatted.push(["P/E", String((detail.pe_ratio as number).toFixed(1))]);
    if (detail.profit_margin != null) formatted.push(["Profit margin", `${((detail.profit_margin as number) * 100).toFixed(1)}%`]);
    if (detail.roe != null) formatted.push(["ROE", `${((detail.roe as number) * 100).toFixed(1)}%`]);
  }

  // Fallback: show any remaining non-skipped fields
  if (formatted.length === 0) {
    for (const [k, v] of Object.entries(detail)) {
      if (skip.has(k) || v == null) continue;
      formatted.push([k.replace(/_/g, " "), String(v)]);
    }
  }

  if (formatted.length === 0) return null;

  return (
    <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5">
      {formatted.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-2 col-span-1">
          <dt className="text-content-muted truncate">{label}</dt>
          <dd className="num font-medium text-content shrink-0">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── Technicals section ────────────────────────────────────────────────────────

function TechnicalsSection({ result }: { result: TechnicalsResult }) {
  const { t } = useTranslation("discover");
  if (result.error || (!result.sma && !result.rsi)) {
    return (
      <section className="card mb-3">
        <h3 className="text-sm font-semibold">{t("drawer.technicalsTitle")}</h3>
        <p className="mt-2 text-xs text-content-muted">{result.error ?? t("drawer.noTechnicals")}</p>
      </section>
    );
  }

  const rsiVal = result.rsi?.value;
  const RSI_LABELS: Record<string, string> = {
    overbought: t("drawer.rsiRange.overbought"),
    overbought_zone: t("drawer.rsiRange.overbought_zone"),
    neutral: t("drawer.rsiRange.neutral"),
    oversold_zone: t("drawer.rsiRange.oversold_zone"),
    oversold: t("drawer.rsiRange.oversold"),
  };
  const rsiLabel = rsiVal != null ? (RSI_LABELS[rsiRangeKey(rsiVal)] ?? null) : null;

  return (
    <section className="card mb-3">
      <h3 className="text-sm font-semibold">{t("drawer.technicalsTitle")}</h3>
      <div className="mt-3 grid grid-cols-2 gap-4 text-xs">
        {result.rsi && (
          <div>
            <p className="text-overline uppercase text-content-muted">{t("drawer.rsiPeriod", { period: result.rsi.period })}</p>
            <p className="num text-2xl font-semibold leading-tight">{rsiVal?.toFixed(1) ?? "—"}</p>
            {rsiLabel && (
              <p className={cn(
                "text-[11px] font-medium mt-0.5",
                result.rsi.signal === "overbought" ? "text-warning"
                : result.rsi.signal === "oversold" ? "text-gain"
                : "text-content-muted",
              )}>
                {rsiLabel}
              </p>
            )}
            {/* Mini RSI gauge */}
            {rsiVal != null && (
              <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-surface-raised">
                <div
                  className={cn(
                    "h-full",
                    rsiVal >= 70 ? "bg-warning"
                    : rsiVal >= 50 ? "bg-gain"
                    : rsiVal >= 30 ? "bg-accent"
                    : "bg-loss",
                  )}
                  style={{ width: `${rsiVal}%` }}
                />
              </div>
            )}
          </div>
        )}
        {result.sma && (
          <div>
            <p className="text-overline uppercase text-content-muted">{t("drawer.smaPeriod", { period: result.sma.period })}</p>
            <p className="num text-2xl font-semibold leading-tight">{result.sma.value?.toFixed(2) ?? "—"}</p>
            <p className={cn(
              "text-[11px] font-medium mt-0.5",
              result.sma.signal === "above_sma" ? "text-gain"
              : result.sma.signal === "below_sma" ? "text-loss"
              : "text-content-muted",
            )}>
              {result.sma.signal && result.sma.signal !== "n/a"
                ? t(`drawer.smaSignal.${result.sma.signal}`, { defaultValue: result.sma.signal })
                : "—"}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Dividend section ──────────────────────────────────────────────────────────

function DividendSection({ result }: { result: DividendResult }) {
  const { t } = useTranslation("discover");
  if (result.error || !result.yield) return null;
  const yld = (result.yield ?? 0) * (result.yield && result.yield < 1 ? 100 : 1);
  return (
    <section className="card mb-3">
      <h3 className="text-sm font-semibold">{t("drawer.dividendTitle")}</h3>
      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-overline uppercase text-content-muted">{t("drawer.dividendYield")}</p>
          <p className="num text-xl font-semibold text-gain">{yld.toFixed(2)}%</p>
        </div>
        {result.safety_score != null && (
          <div>
            <p className="text-overline uppercase text-content-muted">{t("drawer.dividendSafety")}</p>
            <p className="num text-xl font-semibold">{Math.round(result.safety_score)}/100</p>
          </div>
        )}
        {result.income_rating && (
          <div>
            <p className="text-overline uppercase text-content-muted">{t("drawer.dividendRating")}</p>
            <p className="text-xl font-semibold">
              {t(`drawer.dividendRatingValue.${result.income_rating}`, { defaultValue: result.income_rating })}
            </p>
          </div>
        )}
      </div>
      {result.consecutive_increases != null && result.consecutive_increases > 0 && (
        <p className="mt-2 text-[11px] text-content-muted">
          {t("drawer.dividendStreak", { years: result.consecutive_increases })}
        </p>
      )}
    </section>
  );
}

// ── News section ──────────────────────────────────────────────────────────────

function NewsSection({ articles }: { articles: NewsArticle[] }) {
  const { t } = useTranslation("discover");
  return (
    <section className="card">
      <h3 className="text-sm font-semibold">{t("drawer.newsTitle")}</h3>
      <ul className="mt-2 divide-y divide-line">
        {articles.map((a, i) => (
          <li key={i} className="py-2">
            <a
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start justify-between gap-2 text-xs hover:text-accent"
            >
              <span>
                <p className="font-medium leading-snug">{a.title}</p>
                <p className="mt-0.5 text-[10px] text-content-muted">
                  {a.source}{a.published_at ? ` · ${a.published_at.slice(0, 10)}` : ""}
                </p>
              </span>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-content-muted group-hover:text-accent" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
