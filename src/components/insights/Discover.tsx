/**
 * Discover — terminal-grade market view.
 *
 * UX improvements:
 * - Progressive loading: each section reveals as its data arrives (no single blocker)
 * - Watchlist now includes crypto holdings (uses new crypto 8-dim analysis)
 * - Asset-class badges per watchlist row (Stock / ETF / Crypto)
 * - MostActive and MoversCard show price alongside % change
 * - TrendingCrypto shows price when available and "search trend" rank context
 * - RumorsCard highlights high-impact items (score ≥ 7) with accent ring
 * - MarketPulse labels corrected: "Crypto Market Cap", "Stock breadth"
 * - Skeleton cards replace the single full-page spinner
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Flame, AlertTriangle, Loader2, ExternalLink,
  TrendingUp, TrendingDown, Newspaper, Zap,
  Globe, Shield, Target, Activity, Bitcoin,
} from "lucide-react";
import {
  getTrends, getRumors, listPortfolio, getProfile, searchNews,
  analyzeEightDim, getTechnicals,
  type TrendsResult, type RumorItem, type UserProfile, type NewsArticle,
  type Holding, type EightDimResult, type TechnicalsResult,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { DivergingBar, RsiGauge, ProgressTrack } from "@/components/ui/dataviz";
import { TickerDrawer } from "./TickerDrawer";
import { ShortTermSignals } from "./ShortTermSignals";

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtB(n: number | undefined | null) {
  if (n == null) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(0)}B`;
  return `$${n.toFixed(0)}`;
}

function fmtPrice(n: number | null | undefined) {
  if (n == null) return null;
  if (n >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

function CardSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="card animate-pulse space-y-3">
      <div className="h-3 w-1/3 rounded bg-surface-raised" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 rounded bg-surface-raised" />
      ))}
    </div>
  );
}

function RiskBadge({ profile }: { profile: UserProfile["risk_profile"] }) {
  const { t } = useTranslation("discover");
  const styles = {
    conservative: "bg-emerald-950 text-emerald-300 border-emerald-700",
    balanced: "bg-yellow-950 text-yellow-300 border-yellow-700",
    aggressive: "bg-red-950 text-red-300 border-red-700",
  };
  const icons = { conservative: Shield, balanced: Target, aggressive: Zap };
  const Icon = icons[profile];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium", styles[profile])}>
      <Icon className="h-3 w-3" />
      {t(`risk.${profile}`)}
    </span>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export function Discover() {
  const { t } = useTranslation("discover");

  // Independent loading states — sections reveal as each data arrives
  const [trends, setTrends] = useState<TrendsResult | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(true);

  const [rumors, setRumors] = useState<RumorItem[]>([]);
  const [rumorsLoading, setRumorsLoading] = useState(true);

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [portfolioLoading, setPortfolioLoading] = useState(true);

  const [news, setNews] = useState<NewsArticle[]>([]);
  const [newsLoading, setNewsLoading] = useState(true);

  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Wave 1: market data + profile + portfolio (fast, can show skeleton immediately)
    getTrends()
      .catch(() => null)
      .then((tr) => { if (!cancelled) { setTrends(tr); setTrendsLoading(false); } });

    Promise.all([
      getProfile().catch(() => null),
      listPortfolio().catch(() => ({ holdings: [], totals: null })),
    ]).then(([pr, port]) => {
      if (cancelled) return;
      setProfile(pr);
      setHoldings((port as { holdings: Holding[] }).holdings ?? []);
      setPortfolioLoading(false);
    });

    // Wave 2: slower/secondary data
    getRumors()
      .catch(() => [])
      .then((ru) => { if (!cancelled) { setRumors(ru); setRumorsLoading(false); } });

    searchNews("market finance economy", 6)
      .catch(() => [])
      .then((nw) => { if (!cancelled) { setNews(nw); setNewsLoading(false); } });

    return () => { cancelled = true; };
  }, []);

  const asOf = trends?.as_of
    ? new Date(trends.as_of).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="text-sm text-content-muted">{t("subtitle")}</p>
      </header>

      {/* Personalized banner — shows as soon as profile loads */}
      {!portfolioLoading && profile && <PersonalizedBanner profile={profile} />}

      {/* Market-pulse strip */}
      {trendsLoading
        ? <CardSkeleton rows={1} />
        : <MarketPulse trends={trends} asOf={asOf} />}

      {/* 4-hour crypto signal desk — news + technicals + derivatives fusion */}
      <ShortTermSignals />

      {/* Watchlist + Movers — side by side on large screens */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {portfolioLoading
          ? <div className="lg:col-span-7"><CardSkeleton rows={5} /></div>
          : <Watchlist holdings={holdings} onPick={setActive} />}
        {trendsLoading
          ? <div className="lg:col-span-5"><CardSkeleton rows={6} /></div>
          : <MoversCard trends={trends} onPick={setActive} />}
      </div>

      {/* Most active + Trending crypto */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {trendsLoading
          ? <CardSkeleton rows={4} />
          : <MostActiveCard trends={trends} onPick={setActive} />}
        {trendsLoading
          ? <CardSkeleton rows={4} />
          : <TrendingCryptoCard trends={trends} onPick={setActive} />}
      </div>

      {/* Portfolio spotlight — only when portfolio loaded and non-empty */}
      {!portfolioLoading && holdings.length > 0 && (
        <PortfolioSpotlight holdings={holdings} trends={trends} onPick={setActive} />
      )}

      {/* News + Rumors */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {newsLoading
          ? <CardSkeleton rows={5} />
          : news.length > 0 && <NewsSection articles={news} />}
        {rumorsLoading
          ? <CardSkeleton rows={4} />
          : <RumorsCard rumors={rumors} onPick={setActive} />}
      </div>

      <TickerDrawer ticker={active} onClose={() => setActive(null)} />
    </div>
  );
}

// ── PersonalizedBanner ────────────────────────────────────────────────────────

function PersonalizedBanner({ profile }: { profile: UserProfile }) {
  const { t } = useTranslation("discover");
  const tip = t(`riskTip.${profile.risk_profile}`);
  return (
    <div className="card flex items-start gap-4 border-l-4 border-l-accent bg-gradient-to-r from-surface-raised to-surface-raised">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/10 text-lg font-bold text-accent">
        {profile.name?.[0]?.toUpperCase() ?? "?"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{t("personalizedFor", { name: profile.name })}</span>
          <RiskBadge profile={profile.risk_profile} />
        </div>
        <p className="mt-1 text-xs text-content-muted">{tip}</p>
      </div>
    </div>
  );
}

// ── MarketPulse strip ─────────────────────────────────────────────────────────

function MarketPulse({ trends, asOf }: { trends: TrendsResult | null; asOf: string | null }) {
  const { t } = useTranslation("discover");
  const g = trends?.crypto_global;
  const change = g?.market_cap_change_pct_24h;
  const isUp = (change ?? 0) >= 0;
  const gainers = trends?.top_gainers ?? [];
  const losers = trends?.top_losers ?? [];
  const total = gainers.length + losers.length;
  const breadth = total > 0
    ? Math.round((gainers.length / total) * 100)
    : null;

  const stats = [
    {
      label: t("cryptoMarketCap"),
      value: fmtB(g?.market_cap_usd),
      icon: Globe,
      color: undefined as string | undefined,
      hint: "Total crypto market capitalisation",
    },
    {
      label: t("btcDominance"),
      value: g?.btc_dominance != null ? `${g.btc_dominance.toFixed(1)}%` : "—",
      icon: Bitcoin,
      color: undefined,
      hint: "BTC share of total crypto market cap",
    },
    {
      label: t("marketChange24h"),
      value: change != null ? `${isUp ? "+" : ""}${change.toFixed(2)}%` : "—",
      icon: isUp ? TrendingUp : TrendingDown,
      color: isUp ? "text-gain" : "text-loss",
      hint: "24h change in total crypto market cap",
    },
    {
      label: t("mostActive"),
      value: String(trends?.most_active?.length ?? "—"),
      icon: Activity,
      color: "text-accent",
      hint: "Number of most-traded stocks today",
    },
    {
      label: t("stockBreadth"),
      value: breadth != null ? `${breadth}%` : "—",
      icon: breadth != null && breadth >= 50 ? TrendingUp : TrendingDown,
      color: breadth != null && breadth >= 50 ? "text-gain" : "text-loss",
      hint: "% of tracked stocks closing up today",
    },
  ];

  return (
    <div className="card">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map(({ label, value, icon: Icon, color, hint }) => (
          <div key={label} className="group flex items-center gap-2" title={hint}>
            <Icon className={cn("h-4 w-4 shrink-0 text-content-muted", color)} />
            <div className="min-w-0">
              <p className="truncate text-overline uppercase text-content-muted">{label}</p>
              <p className={cn("num text-sm font-semibold", color)}>{value}</p>
            </div>
          </div>
        ))}
      </div>
      {asOf && (
        <p className="mt-2 text-right text-[10px] text-content-muted">{t("updatedAt", { time: asOf })}</p>
      )}
    </div>
  );
}

// ── Watchlist (8-dim score + RSI, lazily fetched per row) ─────────────────────

interface RowAnalysis {
  loading: boolean;
  score: number | null;
  recommendation: string | null;
  rsi: number | null;
  assetClass: string;
}

function assetClassBadge(cls: string) {
  const map: Record<string, string> = {
    stock: "bg-blue-500/10 text-blue-300",
    etf: "bg-purple-500/10 text-purple-300",
    crypto: "bg-yellow-500/10 text-yellow-300",
    fund: "bg-teal-500/10 text-teal-300",
  };
  return map[cls] ?? "bg-surface-raised text-content-muted";
}

function Watchlist({ holdings, onPick }: { holdings: Holding[]; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");

  // Include stocks, ETFs, and crypto (we now have 8-dim for crypto)
  const eligibleHoldings = holdings.filter(
    (h) => h.asset_class === "stock" || h.asset_class === "etf" || h.asset_class === "crypto",
  );
  const uniqueHoldings = Array.from(
    new Map(eligibleHoldings.map((h) => [h.ticker.toUpperCase(), h])).values(),
  ).slice(0, 8);

  const [byTicker, setByTicker] = useState<Record<string, RowAnalysis>>({});

  useEffect(() => {
    let cancelled = false;
    if (uniqueHoldings.length === 0) return;
    setByTicker(
      Object.fromEntries(
        uniqueHoldings.map((h) => [
          h.ticker.toUpperCase(),
          { loading: true, score: null, recommendation: null, rsi: null, assetClass: h.asset_class },
        ]),
      ),
    );

    uniqueHoldings.forEach(async (holding) => {
      const tk = holding.ticker.toUpperCase();
      // Crypto stored as "BTC" → analyze as "BTC-USD"; already "BTC-USD" → keep
      const analysisKey =
        holding.asset_class === "crypto" && !tk.endsWith("-USD") ? `${tk}-USD` : tk;

      const [dim, tech] = await Promise.all([
        analyzeEightDim(analysisKey, true).catch(() => null) as Promise<EightDimResult | null>,
        // Technicals work for crypto too (yfinance handles BTC-USD)
        getTechnicals(analysisKey).catch(() => null) as Promise<TechnicalsResult | null>,
      ]);
      if (cancelled) return;
      setByTicker((prev) => ({
        ...prev,
        [tk]: {
          loading: false,
          score: dim?.final_score != null ? dim.final_score * 100 : null,
          recommendation: dim?.recommendation ?? null,
          rsi: tech?.rsi?.value ?? null,
          assetClass: holding.asset_class,
        },
      }));
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uniqueHoldings.map((h) => h.ticker).join(",")]);

  return (
    <section className="card lg:col-span-7">
      <header className="mb-3 flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("watchlist")}</h2>
        <span className="ml-auto text-[10px] text-content-muted">{t("watchlistCryptoHint")}</span>
      </header>

      {uniqueHoldings.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-4 text-center text-xs text-content-muted">
          {t("watchlistEmpty")}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {uniqueHoldings.map((holding) => {
            const tk = holding.ticker.toUpperCase();
            const a = byTicker[tk];
            const cls = a?.assetClass ?? holding.asset_class;
            return (
              <li key={tk}>
                <button
                  onClick={() => {
                    const key =
                      holding.asset_class === "crypto" && !tk.endsWith("-USD")
                        ? `${tk}-USD`
                        : tk;
                    onPick(key);
                  }}
                  className="flex w-full items-center gap-3 rounded-lg border border-line bg-surface-raised px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent/5"
                >
                  {/* Ticker + asset class badge */}
                  <div className="flex w-20 shrink-0 flex-col gap-0.5">
                    <span className="num text-xs font-semibold leading-tight">{tk}</span>
                    <span className={cn(
                      "w-fit rounded px-1 py-0 text-overline uppercase",
                      assetClassBadge(cls),
                    )}>
                      {t(`assetClass.${cls}`, { defaultValue: cls })}
                    </span>
                  </div>

                  {!a || a.loading ? (
                    <span className="flex flex-1 items-center gap-2 text-[11px] text-content-muted">
                      <Loader2 className="h-3 w-3 animate-spin" /> {t("scoring")}
                    </span>
                  ) : (
                    <>
                      <RecommendationBadge rec={a.recommendation} />
                      <div className="flex flex-1 items-center gap-2">
                        <ProgressTrack
                          pct={a.score ?? 0}
                          color={(a.score ?? 0) >= 60 ? "#22C55E" : (a.score ?? 0) >= 40 ? "#F59E0B" : "#EF4444"}
                        />
                        <span className="num w-8 shrink-0 text-right text-[11px] text-content-muted">
                          {a.score != null ? Math.round(a.score) : "—"}
                        </span>
                      </div>
                      <RsiGauge value={a.rsi} className="w-[72px] shrink-0 justify-end" />
                    </>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function RecommendationBadge({ rec }: { rec: string | null }) {
  const { t } = useTranslation("discover");
  if (!rec) return <span className="w-12 shrink-0" />;
  const r = rec.toLowerCase();
  const kind = r.includes("buy") ? "buy" : r.includes("sell") ? "sell" : "hold";
  const cls =
    kind === "buy" ? "bg-gain/15 text-gain"
    : kind === "sell" ? "bg-loss/15 text-loss"
    : "bg-surface text-content-muted";
  return (
    <span className={cn("w-12 shrink-0 rounded-full px-2 py-0.5 text-center text-overline uppercase", cls)}>
      {t(`recommendation.${kind}`)}
    </span>
  );
}

// ── MoversCard (diverging bars + price) ──────────────────────────────────────

function MoversCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const gainers = (trends?.top_gainers ?? []).slice(0, 4);
  const losers = (trends?.top_losers ?? []).slice(0, 4);
  const rows = [
    ...gainers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0, price: g.price })),
    ...losers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0, price: g.price })),
  ].sort((a, b) => b.pct - a.pct);
  const max = Math.max(...rows.map((r) => Math.abs(r.pct)), 1);

  return (
    <section className="card lg:col-span-5">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("movers")}</h2>
      </header>
      {rows.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noTrendData")}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.ticker}>
              <button
                onClick={() => onPick(r.ticker)}
                className="group w-full text-left transition hover:opacity-80"
              >
                <DivergingBar pct={r.pct} max={max} label={r.ticker} />
                {/* Price below bar */}
                {r.price != null && (
                  <p className="mt-0.5 text-right text-[10px] text-content-muted num">
                    {fmtPrice(r.price)}
                  </p>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── MostActiveCard (with price) ───────────────────────────────────────────────

function MostActiveCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const active = (trends?.most_active ?? []).slice(0, 8);
  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("mostActive")}</h2>
      </header>
      {active.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noTrendData")}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {active.map((a) => {
            const up = (a.change_pct ?? 0) >= 0;
            return (
              <li key={a.ticker}>
                <button
                  onClick={() => onPick(a.ticker)}
                  className="flex w-full flex-col rounded-lg border border-line bg-surface-raised px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent/5"
                >
                  <div className="flex w-full items-center justify-between gap-1">
                    <span className="num text-xs font-semibold">{a.ticker}</span>
                    <span className={cn("num text-[11px] font-medium", up ? "text-gain" : "text-loss")}>
                      {up ? "+" : ""}{(a.change_pct ?? 0).toFixed(1)}%
                    </span>
                  </div>
                  {a.price != null && (
                    <p className="num mt-0.5 text-[10px] text-content-muted">{fmtPrice(a.price)}</p>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── TrendingCryptoCard (with price + rank context) ────────────────────────────

function TrendingCryptoCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const crypto = trends?.crypto_trending?.slice(0, 8) ?? [];

  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("trendingCrypto")}</h2>
        <span
          className="ml-auto cursor-help text-[10px] text-content-muted underline-offset-2 hover:underline"
          title="Ranked by CoinGecko search volume in the last 24 hours"
        >
          {t("searchTrend")}
        </span>
      </header>

      {crypto.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noTrendData")}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {crypto.map((c, i) => (
            <li key={c.symbol}>
              <button
                onClick={() => onPick(`${c.symbol.toUpperCase()}-USD`)}
                className="flex w-full items-center gap-2.5 rounded-lg border border-line bg-surface-raised px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent/5"
              >
                {/* Rank medal */}
                <span className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                  i === 0 ? "bg-yellow-500/20 text-yellow-300"
                    : i === 1 ? "bg-slate-400/20 text-slate-300"
                    : i === 2 ? "bg-orange-700/20 text-orange-400"
                    : "bg-surface text-content-muted",
                )}>
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-1">
                    <p className="font-mono text-xs font-semibold uppercase leading-tight">{c.symbol}</p>
                    {c.price_usd != null && (
                      <p className="num text-[10px] text-content-muted shrink-0">{fmtPrice(c.price_usd)}</p>
                    )}
                  </div>
                  <p className="truncate text-[10px] text-content-muted">{c.name}</p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── PortfolioSpotlight ────────────────────────────────────────────────────────

function PortfolioSpotlight({
  holdings, trends, onPick,
}: {
  holdings: Holding[];
  trends: TrendsResult | null;
  onPick: (t: string) => void;
}) {
  const { t } = useTranslation("discover");
  const myTickers = new Set(holdings.map((h) => h.ticker.toUpperCase()));

  const gainersHit = (trends?.top_gainers ?? []).filter((g) => myTickers.has(g.ticker.toUpperCase()));
  const losersHit = (trends?.top_losers ?? []).filter((g) => myTickers.has(g.ticker.toUpperCase()));
  const allHits = [
    ...gainersHit.map((g) => ({ ...g, type: "gain" as const })),
    ...losersHit.map((g) => ({ ...g, type: "loss" as const })),
  ];

  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Target className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("portfolioSpotlight")}</h2>
      </header>

      {allHits.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noPortfolioOverlap")}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {allHits.map((h) => (
            <button
              key={h.ticker}
              onClick={() => onPick(h.ticker)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                h.type === "gain"
                  ? "border-gain/30 bg-gain/10 text-gain hover:bg-gain/20"
                  : "border-loss/30 bg-loss/10 text-loss hover:bg-loss/20",
              )}
            >
              {h.type === "gain" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              <span className="font-mono font-semibold">{h.ticker}</span>
              <span className="opacity-80">
                {h.type === "gain" ? "+" : ""}{h.change_pct?.toFixed(2) ?? "?"}%
              </span>
              {h.price != null && (
                <span className="num opacity-60">{fmtPrice(h.price)}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

// ── NewsSection ───────────────────────────────────────────────────────────────

function NewsSection({ articles }: { articles: NewsArticle[] }) {
  const { t } = useTranslation("discover");
  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Newspaper className="h-4 w-4 text-content-muted" />
        <h2 className="text-sm font-semibold">{t("latestNews")}</h2>
      </header>
      <ul className="divide-y divide-line">
        {articles.slice(0, 6).map((a, i) => (
          <li key={i} className="py-2.5">
            <a
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-2 text-xs hover:text-accent"
            >
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded bg-surface-raised text-[10px] text-content-muted">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="leading-snug group-hover:underline">{a.title}</p>
                <p className="mt-0.5 text-[10px] text-content-muted">
                  {a.source}
                  {a.published_at
                    ? ` · ${new Date(a.published_at).toLocaleDateString([], { month: "short", day: "numeric" })}`
                    : ""}
                </p>
              </div>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-content-muted opacity-0 group-hover:opacity-100" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── RumorsCard ────────────────────────────────────────────────────────────────

function ImpactDots({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-0.5" title={`Impact: ${score}/10`}>
      {Array.from({ length: 5 }).map((_, i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            i < Math.ceil(score / 2)
              ? score >= 7 ? "bg-warning" : "bg-accent"
              : "bg-surface-raised",
          )}
        />
      ))}
    </div>
  );
}

function RumorsCard({ rumors, onPick }: { rumors: RumorItem[]; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("rumorMill")}</h2>
      </header>
      {rumors.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noRumors")}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rumors.slice(0, 8).map((r, i) => {
            const isUp = r.sentiment_label === "Bullish" || r.sentiment_label === "Somewhat-Bullish";
            const isDown = r.sentiment_label === "Bearish" || r.sentiment_label === "Somewhat-Bearish";
            const isHighImpact = (r.impact_score ?? 0) >= 7;
            const SentIcon = isUp ? TrendingUp : isDown ? TrendingDown : null;
            const edgeColor = isUp ? "border-l-gain" : isDown ? "border-l-loss" : "border-l-line";

            return (
              <li
                key={i}
                className={cn(
                  "border-l-2 py-2 pl-2 text-xs",
                  edgeColor,
                  // High-impact items get a subtle background highlight
                  isHighImpact && "rounded-r-md bg-warning/5",
                )}
              >
                {/* Top row: category badge + ticker + impact */}
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 text-overline uppercase",
                    r.category === "m&a" ? "bg-accent-muted text-accent" : "bg-surface-raised text-content-muted",
                  )}>
                    {r.category ?? "news"}
                  </span>
                  {r.ticker && (
                    <button
                      onClick={() => onPick(r.ticker!)}
                      className="font-mono font-semibold text-emerald-300 hover:text-accent"
                    >
                      {r.ticker}
                    </button>
                  )}
                  <div className="ml-auto flex items-center gap-1.5">
                    {isHighImpact && (
                      <span className="text-overline uppercase text-warning">
                        {t("highImpact")}
                      </span>
                    )}
                    {r.impact_score != null && <ImpactDots score={r.impact_score} />}
                    <span className="num text-[10px] text-content-muted">{t("impact", { score: r.impact_score })}</span>
                  </div>
                </div>

                {/* Headline link */}
                <a
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 flex items-start justify-between gap-2 leading-snug hover:text-accent"
                >
                  <span>{r.title}</span>
                  <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-content-muted" />
                </a>

                {/* Sentiment + source */}
                {r.sentiment_label && (
                  <p className={cn(
                    "mt-1 flex items-center gap-1 text-[10px]",
                    isUp ? "text-gain" : isDown ? "text-loss" : "text-content-muted",
                  )}>
                    {SentIcon && <SentIcon className="h-3 w-3" />}
                    {r.sentiment_label}
                    {r.source ? ` · ${r.source}` : ""}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
