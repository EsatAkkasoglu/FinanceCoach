/**
 * Discover — personalized market overview with infographics.
 * Sections: personalized header, global crypto bar, movers chart,
 * trending crypto, portfolio spotlight, latest news, rumor mill.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Flame, AlertTriangle, Loader2, ExternalLink,
  TrendingUp, TrendingDown, Newspaper, Zap,
  Globe, Shield, Target,
} from "lucide-react";
import {
  BarChart, Bar, Cell, XAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  getTrends, getRumors, listPortfolio, getProfile, searchNews,
  type TrendsResult, type RumorItem, type UserProfile, type NewsArticle,
  type Holding,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { chartTooltip, GAIN, LOSS } from "@/lib/chartColors";
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
    <div className="space-y-5">
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

          {/* Global crypto macro bar */}
          {trends?.crypto_global && (
            <GlobalCryptoBar global={trends.crypto_global} asOf={asOf} />
          )}

          {/* Movers + trending crypto */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <MoversCard trends={trends} onPick={setActive} />
            <TrendingCryptoCard trends={trends} onPick={setActive} />
          </div>

          {/* Portfolio spotlight */}
          {holdings.length > 0 && (
            <PortfolioSpotlight holdings={holdings} trends={trends} onPick={setActive} />
          )}

          {/* News feed */}
          {news.length > 0 && <NewsSection articles={news} />}

          {/* Rumor mill */}
          <RumorsCard rumors={rumors} onPick={setActive} />
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

// ── GlobalCryptoBar ───────────────────────────────────────────────────────────

function GlobalCryptoBar({
  global,
  asOf,
}: {
  global: NonNullable<TrendsResult["crypto_global"]>;
  asOf: string | null;
}) {
  const { t } = useTranslation("discover");
  const change = global.market_cap_change_pct_24h;
  const isUp = (change ?? 0) >= 0;

  const stats = [
    { label: t("globalMarketCap"), value: fmtB(global.market_cap_usd), icon: Globe, color: undefined as string | undefined },
    {
      label: t("btcDominance"),
      value: global.btc_dominance != null ? `${global.btc_dominance.toFixed(1)}%` : "—",
      icon: Flame,
      color: undefined as string | undefined,
    },
    {
      label: t("marketChange24h"),
      value: change != null ? `${isUp ? "+" : ""}${change.toFixed(2)}%` : "—",
      icon: isUp ? TrendingUp : TrendingDown,
      color: isUp ? "text-gain" : "text-loss",
    },
  ];

  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-4">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="flex items-center gap-2 min-w-[110px]">
            <Icon className={cn("h-4 w-4 shrink-0 text-content-muted", color)} />
            <div>
              <p className="text-[10px] uppercase tracking-widest text-content-muted">{label}</p>
              <p className={cn("text-sm font-semibold num", color)}>{value}</p>
            </div>
          </div>
        ))}
        {asOf && (
          <span className="ml-auto text-[10px] text-content-muted">
            {t("updatedAt", { time: asOf })}
          </span>
        )}
      </div>
    </div>
  );
}

// ── MoversCard ────────────────────────────────────────────────────────────────

function MoversCard({
  trends,
  onPick,
}: {
  trends: TrendsResult | null;
  onPick: (t: string) => void;
}) {
  const { t } = useTranslation("discover");
  const gainers = (trends?.top_gainers ?? []).slice(0, 5);
  const losers = (trends?.top_losers ?? []).slice(0, 5);

  const chartData = [
    ...gainers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0, type: "gain" as const })),
    ...losers.map((g) => ({ ticker: g.ticker, pct: g.change_pct ?? 0, type: "loss" as const })),
  ].sort((a, b) => b.pct - a.pct);

  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("hotToday")}</h2>
      </header>

      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 8, left: 4, bottom: 0 }}
            onClick={(s) => {
              const ticker = s?.activePayload?.[0]?.payload?.ticker;
              if (ticker) onPick(ticker);
            }}
            style={{ cursor: "pointer" }}
          >
            <XAxis type="number" tickFormatter={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip
              formatter={(v: number) => [`${v > 0 ? "+" : ""}${v.toFixed(2)}%`, ""]}
              {...chartTooltip}
            />
            <Bar dataKey="pct" radius={[0, 4, 4, 0]} maxBarSize={18}>
              {chartData.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.type === "gain" ? GAIN : LOSS}
                  fillOpacity={0.85}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p className="text-xs text-content-muted">{t("noTrendData")}</p>
      )}

      {/* XAxis label */}
      {chartData.length > 0 && (
        <div className="mt-1 flex justify-between text-[10px] text-content-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-gain/70" />
            {t("topGainers")}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm bg-loss/70" />
            {t("topLosers")}
          </span>
        </div>
      )}
    </section>
  );
}

// ── TrendingCryptoCard ────────────────────────────────────────────────────────

function TrendingCryptoCard({
  trends,
  onPick,
}: {
  trends: TrendsResult | null;
  onPick: (t: string) => void;
}) {
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
                {/* Rank badge */}
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
  holdings,
  trends,
  onPick,
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
            return (
              <li key={i} className="py-2 text-xs">
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
