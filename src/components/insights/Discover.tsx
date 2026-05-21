/**
 * Discover — terminal-grade market view.
 * Sections: market-pulse strip, watchlist grid (8-dim score + RSI, lazy-loaded),
 * diverging movers, most active, trending crypto, sentiment-weighted news, rumors.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Flame, AlertTriangle, Loader2, ExternalLink,
  TrendingUp, TrendingDown, Newspaper, Zap,
  Globe, Shield, Target, Activity,
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

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtB(n: number | undefined) {
  if (n == null) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(0)}B`;
  return `$${n.toFixed(0)}`;
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
  const [trends, setTrends] = useState<TrendsResult | null>(null);
  const [rumors, setRumors] = useState<RumorItem[]>([]);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getTrends().catch(() => null),
      getRumors().catch(() => []),
      getProfile().catch(() => null),
      listPortfolio().catch(() => ({ holdings: [], totals: null })),
      searchNews("market finance economy", 6).catch(() => []),
    ]).then(([tr, ru, pr, port, nw]) => {
      if (cancelled) return;
      setTrends(tr);
      setRumors(ru);
      setProfile(pr);
      setHoldings((port as { holdings: Holding[] }).holdings ?? []);
      setNews(nw);
      setLoading(false);
    });
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

      {loading ? (
        <div className="card flex h-40 items-center justify-center text-content-muted">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : (
        <>
          {/* Personalized banner */}
          {profile && <PersonalizedBanner profile={profile} />}

          {/* Market-pulse strip */}
          <MarketPulse trends={trends} asOf={asOf} />

          {/* Watchlist (8-dim + RSI) + movers */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <Watchlist holdings={holdings} onPick={setActive} />
            <MoversCard trends={trends} onPick={setActive} />
          </div>

          {/* Most active + trending crypto */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <MostActiveCard trends={trends} onPick={setActive} />
            <TrendingCryptoCard trends={trends} onPick={setActive} />
          </div>

          {/* Portfolio spotlight */}
          {holdings.length > 0 && (
            <PortfolioSpotlight holdings={holdings} trends={trends} onPick={setActive} />
          )}

          {/* News + rumors */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {news.length > 0 && <NewsSection articles={news} />}
            <RumorsCard rumors={rumors} onPick={setActive} />
          </div>
        </>
      )}

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
  const breadth = gainers.length + losers.length > 0
    ? Math.round((gainers.length / (gainers.length + losers.length)) * 100)
    : null;

  const stats = [
    { label: t("globalMarketCap"), value: fmtB(g?.market_cap_usd), icon: Globe, color: undefined as string | undefined },
    { label: t("btcDominance"), value: g?.btc_dominance != null ? `${g.btc_dominance.toFixed(1)}%` : "—", icon: Flame, color: undefined },
    { label: t("marketChange24h"), value: change != null ? `${isUp ? "+" : ""}${change.toFixed(2)}%` : "—", icon: isUp ? TrendingUp : TrendingDown, color: isUp ? "text-gain" : "text-loss" },
    { label: t("topGainers"), value: String(gainers.length), icon: TrendingUp, color: "text-gain" },
    { label: t("hotToday"), value: breadth != null ? `${breadth}%` : "—", icon: Activity, color: breadth != null && breadth >= 50 ? "text-gain" : "text-loss" },
  ];

  return (
    <div className="card">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="flex items-center gap-2">
            <Icon className={cn("h-4 w-4 shrink-0 text-content-muted", color)} />
            <div className="min-w-0">
              <p className="truncate text-[10px] uppercase tracking-widest text-content-muted">{label}</p>
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
  score: number | null;            // 0-100
  recommendation: string | null;   // buy / hold / sell-ish
  rsi: number | null;
}

function Watchlist({ holdings, onPick }: { holdings: Holding[]; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  // De-dupe equities/ETFs (8-dim is meaningless for cash); cap to keep it snappy.
  const tickers = Array.from(
    new Set(
      holdings
        .filter((h) => h.asset_class === "stock" || h.asset_class === "etf")
        .map((h) => h.ticker.toUpperCase()),
    ),
  ).slice(0, 6);

  const [byTicker, setByTicker] = useState<Record<string, RowAnalysis>>({});

  useEffect(() => {
    let cancelled = false;
    if (tickers.length === 0) return;
    setByTicker(Object.fromEntries(tickers.map((tk) => [tk, { loading: true, score: null, recommendation: null, rsi: null }])));
    tickers.forEach(async (tk) => {
      const [dim, tech] = await Promise.all([
        analyzeEightDim(tk, true).catch(() => null) as Promise<EightDimResult | null>,
        getTechnicals(tk).catch(() => null) as Promise<TechnicalsResult | null>,
      ]);
      if (cancelled) return;
      setByTicker((prev) => ({
        ...prev,
        [tk]: {
          loading: false,
          score: dim?.final_score ?? null,
          recommendation: dim?.recommendation ?? null,
          rsi: tech?.rsi?.value ?? null,
        },
      }));
    });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickers.join(",")]);

  return (
    <section className="card lg:col-span-7">
      <header className="mb-3 flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("watchlist")}</h2>
        <span className="ml-auto text-[10px] text-content-muted">{t("watchlistHint")}</span>
      </header>

      {tickers.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-4 text-center text-xs text-content-muted">
          {t("watchlistEmpty")}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {tickers.map((tk) => {
            const a = byTicker[tk];
            return (
              <li key={tk}>
                <button
                  onClick={() => onPick(tk)}
                  className="flex w-full items-center gap-3 rounded-lg border border-line bg-surface-raised px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent/5"
                >
                  <span className="num w-14 shrink-0 text-xs font-semibold">{tk}</span>
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
    <span className={cn("w-12 shrink-0 rounded-full px-2 py-0.5 text-center text-[10px] font-medium uppercase", cls)}>
      {t(`recommendation.${kind}`)}
    </span>
  );
}

// ── MoversCard (diverging bars) ───────────────────────────────────────────────

function MoversCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const gainers = (trends?.top_gainers ?? []).slice(0, 4);
  const losers = (trends?.top_losers ?? []).slice(0, 4);
  const rows = [
    ...gainers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0 })),
    ...losers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0 })),
  ].sort((a, b) => b.pct - a.pct);
  const max = Math.max(...rows.map((r) => Math.abs(r.pct)), 1);

  return (
    <section className="card lg:col-span-5">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("hotToday")}</h2>
      </header>
      {rows.length === 0 ? (
        <p className="text-xs text-content-muted">{t("noTrendData")}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.ticker}>
              <button
                onClick={() => onPick(r.ticker)}
                aria-label={`${r.ticker} ${r.pct >= 0 ? "+" : ""}${r.pct.toFixed(1)} percent`}
                className="w-full text-left transition hover:opacity-80"
              >
                <DivergingBar pct={r.pct} max={max} label={r.ticker} />
                <span className="sr-only">
                  {r.ticker} {r.pct >= 0 ? "+" : ""}{r.pct.toFixed(1)} percent
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── MostActiveCard ────────────────────────────────────────────────────────────

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
                  className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-surface-raised px-3 py-2 text-left transition-colors hover:border-accent hover:bg-accent/5"
                >
                  <span className="num text-xs font-semibold">{a.ticker}</span>
                  <span className={cn("num text-[11px]", up ? "text-gain" : "text-loss")}>
                    {up ? "+" : ""}{(a.change_pct ?? 0).toFixed(1)}%
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── TrendingCryptoCard ────────────────────────────────────────────────────────

function TrendingCryptoCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const crypto = trends?.crypto_trending?.slice(0, 8) ?? [];

  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold">{t("trendingCrypto")}</h2>
        <span className="ml-auto text-[10px] text-content-muted">{t("rankHint")}</span>
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
                <span className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[9px] font-bold",
                  i === 0 ? "bg-yellow-500/20 text-yellow-300"
                    : i === 1 ? "bg-slate-400/20 text-slate-300"
                    : i === 2 ? "bg-orange-700/20 text-orange-400"
                    : "bg-surface-raised text-content-muted",
                )}>
                  {c.rank ?? i + 1}
                </span>
                <div className="min-w-0">
                  <p className="font-mono text-xs font-semibold uppercase leading-tight">{c.symbol}</p>
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
  const allHits = [...gainersHit.map((g) => ({ ...g, type: "gain" as const })), ...losersHit.map((g) => ({ ...g, type: "loss" as const }))];

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
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-mono font-semibold transition-colors",
                h.type === "gain"
                  ? "border-gain/30 bg-gain/10 text-gain hover:bg-gain/20"
                  : "border-loss/30 bg-loss/10 text-loss hover:bg-loss/20",
              )}
            >
              {h.type === "gain" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {h.ticker}
              <span className="font-normal opacity-80">
                {h.type === "gain" ? "+" : ""}{h.change_pct?.toFixed(2) ?? "?"}%
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

// ── NewsSection (sentiment-weighted) ──────────────────────────────────────────

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
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded bg-surface-raised text-[9px] text-content-muted">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="leading-snug group-hover:underline">{a.title}</p>
                <p className="mt-0.5 text-[10px] text-content-muted">
                  {a.source}
                  {a.published_at ? ` · ${new Date(a.published_at).toLocaleDateString([], { month: "short", day: "numeric" })}` : ""}
                </p>
              </div>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 opacity-0 group-hover:opacity-100 text-content-muted" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── RumorsCard ────────────────────────────────────────────────────────────────

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
            const SentIcon = isUp ? TrendingUp : isDown ? TrendingDown : null;
            const edge = isUp ? "border-l-gain" : isDown ? "border-l-loss" : "border-l-line";
            return (
              <li key={i} className={cn("border-l-2 py-2 pl-2 text-xs", edge)}>
                <div className="flex items-start gap-2">
                  <span className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider",
                    r.category === "m&a" ? "bg-accent-muted text-accent" : "bg-surface-raised text-content-muted",
                  )}>
                    {r.category ?? "news"}
                  </span>
                  {r.ticker && (
                    <button onClick={() => onPick(r.ticker!)} className="font-mono font-semibold text-emerald-300 hover:text-accent">
                      {r.ticker}
                    </button>
                  )}
                  {r.impact_score != null && (
                    <span className="ml-auto text-[10px] text-content-muted">
                      {t("impact", { score: r.impact_score })}
                    </span>
                  )}
                </div>
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="mt-1 flex items-start justify-between gap-2 hover:text-accent">
                  <span className="leading-snug">{r.title}</span>
                  <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-content-muted" />
                </a>
                {r.sentiment_label && SentIcon && (
                  <p className="mt-1 text-[10px] text-content-muted">
                    <SentIcon className="inline h-3 w-3 mr-1" />
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
