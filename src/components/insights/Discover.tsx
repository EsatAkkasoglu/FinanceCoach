/**
 * Discover — hot trends + rumors. Pulls /insights/trends and /insights/rumors.
 * Clicking a row opens the shared TickerDrawer.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Flame, AlertTriangle, Loader2, ExternalLink, TrendingUp, TrendingDown } from "lucide-react";
import {
  getTrends, getRumors,
  type TrendsResult, type RumorItem,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { TickerDrawer } from "./TickerDrawer";

export function Discover() {
  const { t } = useTranslation("discover");
  const [trends, setTrends] = useState<TrendsResult | null>(null);
  const [rumors, setRumors] = useState<RumorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getTrends().catch(() => null), getRumors().catch(() => [])])
      .then(([t, r]) => {
        if (cancelled) return;
        setTrends(t); setRumors(r); setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="text-sm text-[hsl(var(--text-muted))]">
          {t("subtitle")}
        </p>
      </header>

      {loading ? (
        <div className="card flex h-32 items-center justify-center text-[hsl(var(--text-muted))]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <TrendsCard trends={trends} onPick={setActive} />
          <RumorsCard rumors={rumors} onPick={setActive} />
        </div>
      )}

      <TickerDrawer ticker={active} onClose={() => setActive(null)} />
    </div>
  );
}

function TrendsCard({ trends, onPick }: { trends: TrendsResult | null; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  const gainers = trends?.top_gainers?.slice(0, 5) ?? [];
  const losers = trends?.top_losers?.slice(0, 5) ?? [];
  const crypto = trends?.crypto_trending?.slice(0, 5) ?? [];

  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <Flame className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("hotToday")}</h2>
      </header>

      {gainers.length > 0 && (
        <>
          <p className="text-[10px] uppercase tracking-widest text-gain">{t("topGainers")}</p>
          <ul className="mt-1 mb-3 divide-y divide-[hsl(var(--border))]">
            {gainers.map((g) => (
              <li key={g.ticker}>
                <button
                  onClick={() => g.ticker && onPick(g.ticker)}
                  className="flex w-full items-center justify-between py-1.5 text-sm hover:text-accent"
                >
                  <span className="font-mono">{g.ticker}</span>
                  <span className="num text-gain">+{g.change_pct?.toFixed(2) ?? "—"}%</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {losers.length > 0 && (
        <>
          <p className="text-[10px] uppercase tracking-widest text-loss">{t("topLosers")}</p>
          <ul className="mt-1 mb-3 divide-y divide-[hsl(var(--border))]">
            {losers.map((g) => (
              <li key={g.ticker}>
                <button
                  onClick={() => g.ticker && onPick(g.ticker)}
                  className="flex w-full items-center justify-between py-1.5 text-sm hover:text-accent"
                >
                  <span className="font-mono">{g.ticker}</span>
                  <span className="num text-loss">{g.change_pct?.toFixed(2) ?? "—"}%</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {crypto.length > 0 && (
        <>
          <p className="text-[10px] uppercase tracking-widest text-accent">{t("trendingCrypto")}</p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {crypto.map((c) => (
              <li key={c.symbol}>
                <button
                  onClick={() => onPick(`${c.symbol.toUpperCase()}-USD`)}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2.5 py-1 text-xs font-mono hover:border-accent hover:text-accent"
                  title={c.name}
                >
                  {c.symbol.toUpperCase()}
                  {c.rank ? <span className="ml-1 text-[9px] text-[hsl(var(--text-muted))]">#{c.rank}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {gainers.length === 0 && losers.length === 0 && crypto.length === 0 && (
        <p className="text-xs text-[hsl(var(--text-muted))]">
          {t("noTrendData")}
        </p>
      )}
    </section>
  );
}

function RumorsCard({ rumors, onPick }: { rumors: RumorItem[]; onPick: (t: string) => void }) {
  const { t } = useTranslation("discover");
  if (rumors.length === 0) {
    return (
      <section className="card">
        <header className="mb-3 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-warning" />
          <h2 className="text-sm font-semibold">{t("rumorMill")}</h2>
        </header>
        <p className="text-xs text-[hsl(var(--text-muted))]">
          {t("noRumors")}
        </p>
      </section>
    );
  }
  return (
    <section className="card">
      <header className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-warning" />
        <h2 className="text-sm font-semibold">{t("rumorMill")}</h2>
      </header>
      <ul className="divide-y divide-[hsl(var(--border))]">
        {rumors.slice(0, 8).map((r, i) => {
          const SentIcon = r.sentiment_label === "Bullish" || r.sentiment_label === "Somewhat-Bullish"
            ? TrendingUp
            : r.sentiment_label === "Bearish" || r.sentiment_label === "Somewhat-Bearish"
            ? TrendingDown
            : null;
          return (
            <li key={i} className="py-2 text-xs">
              <div className="flex items-start gap-2">
                <span className={cn(
                  "rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider",
                  r.category === "m&a" ? "bg-accent-muted text-accent" : "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))]",
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
                {r.impact_score != null && (
                  <span className="ml-auto text-[10px] text-[hsl(var(--text-muted))]">
                    {t("impact", { score: r.impact_score })}
                  </span>
                )}
              </div>
              <a
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 flex items-start justify-between gap-2 hover:text-accent"
              >
                <span className="leading-snug">{r.title}</span>
                <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--text-muted))]" />
              </a>
              {r.sentiment_label && SentIcon && (
                <p className="mt-1 text-[10px] text-[hsl(var(--text-muted))]">
                  <SentIcon className="inline h-3 w-3 mr-1" />
                  {r.sentiment_label}
                  {r.source ? ` · ${r.source}` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
