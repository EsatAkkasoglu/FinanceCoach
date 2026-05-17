/**
 * TickerDrawer — slide-in detail panel for a US ticker.
 *
 * Lazily fetches: 8-dim analysis, RSI/SMA technicals, latest news, dividend
 * metrics — all in parallel. Used from Portfolio (8-dim badge) and Discover
 * tab (trending / rumored ticker rows).
 */
import { useEffect, useState } from "react";
import { X, Loader2, ExternalLink } from "lucide-react";
import {
  analyzeEightDim, getTechnicals, getDividend, searchNews,
  type EightDimResult, type TechnicalsResult, type DividendResult, type NewsArticle,
} from "@/lib/api";
import { cn } from "@/lib/cn";

interface Props {
  ticker: string | null;
  onClose: () => void;
}

export function TickerDrawer({ ticker, onClose }: Props) {
  const [eight, setEight] = useState<EightDimResult | null>(null);
  const [tech, setTech] = useState<TechnicalsResult | null>(null);
  const [dividend, setDividend] = useState<DividendResult | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setEight(null); setTech(null); setDividend(null); setNews([]);
    Promise.all([
      analyzeEightDim(ticker, true).catch(() => null),
      getTechnicals(ticker).catch(() => null),
      getDividend(ticker).catch(() => null),
      searchNews(ticker, 4).catch(() => []),
    ]).then(([e, t, d, n]) => {
      if (cancelled) return;
      setEight(e); setTech(t); setDividend(d); setNews(n);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [ticker]);

  if (!ticker) return null;

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-[hsl(var(--border))] bg-[hsl(var(--bg))] p-5 shadow-2xl animate-in slide-in-from-right">
        <header className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-[hsl(var(--text-muted))]">Ticker analysis</p>
            <h2 className="font-mono text-3xl font-semibold text-emerald-300">{ticker}</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        {loading && (
          <div className="flex h-32 items-center justify-center text-[hsl(var(--text-muted))]">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="ml-2 text-sm">Analyzing {ticker}…</span>
          </div>
        )}

        {!loading && eight && <EightDimSection result={eight} />}
        {!loading && tech && <TechnicalsSection result={tech} />}
        {!loading && dividend && <DividendSection result={dividend} />}
        {!loading && news.length > 0 && <NewsSection articles={news} />}
      </aside>
    </div>
  );
}

function EightDimSection({ result }: { result: EightDimResult }) {
  if (result.error || result.degraded) {
    return (
      <section className="card mb-3">
        <h3 className="text-sm font-semibold">8-dimension analysis</h3>
        <p className="mt-2 text-xs text-warning">{result.error ?? "Analysis degraded — data unavailable."}</p>
      </section>
    );
  }
  const dims = Object.entries(result.dimensions).map(([key, val]) => ({
    key,
    score: typeof val.score === "number" ? val.score : 0,
  }));
  const rec = result.recommendation ?? "—";
  const recTone =
    rec === "BUY" ? "text-gain"
    : rec === "SELL" ? "text-loss"
    : "text-[hsl(var(--text-muted))]";
  return (
    <section className="card mb-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">8-dimension analysis</h3>
        <div className="text-right">
          <p className={cn("text-lg font-semibold", recTone)}>{rec}</p>
          {result.final_score != null && (
            <p className="text-[10px] text-[hsl(var(--text-muted))]">score {(result.final_score * 100).toFixed(0)}/100</p>
          )}
        </div>
      </div>
      <ul className="mt-3 space-y-1.5">
        {dims.map((d) => (
          <li key={d.key} className="flex items-center gap-2 text-xs">
            <span className="w-32 uppercase text-[10px] tracking-wide text-[hsl(var(--text-muted))]">
              {d.key.replace(/_/g, " ")}
            </span>
            <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
              <div
                className={cn(
                  "h-full",
                  d.score >= 0.7 ? "bg-gain"
                  : d.score >= 0.45 ? "bg-accent"
                  : "bg-loss",
                )}
                style={{ width: `${Math.max(0, Math.min(100, d.score * 100))}%` }}
              />
            </div>
            <span className="num w-8 text-right text-[10px] text-[hsl(var(--text-muted))]">
              {(d.score * 100).toFixed(0)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TechnicalsSection({ result }: { result: TechnicalsResult }) {
  if (result.error || (!result.sma && !result.rsi)) {
    return (
      <section className="card mb-3">
        <h3 className="text-sm font-semibold">Technicals</h3>
        <p className="mt-2 text-xs text-[hsl(var(--text-muted))]">{result.error ?? "No technical data."}</p>
      </section>
    );
  }
  return (
    <section className="card mb-3">
      <h3 className="text-sm font-semibold">Technicals</h3>
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
        {result.rsi && (
          <div>
            <p className="text-[10px] uppercase text-[hsl(var(--text-muted))]">RSI ({result.rsi.period}d)</p>
            <p className="num text-xl font-semibold">{result.rsi.value?.toFixed(1) ?? "—"}</p>
            <p className={cn(
              "text-[10px] capitalize",
              result.rsi.signal === "overbought" && "text-warning",
              result.rsi.signal === "oversold" && "text-gain",
              result.rsi.signal === "neutral" && "text-[hsl(var(--text-muted))]",
            )}>
              {result.rsi.signal}
            </p>
          </div>
        )}
        {result.sma && (
          <div>
            <p className="text-[10px] uppercase text-[hsl(var(--text-muted))]">SMA ({result.sma.period}d)</p>
            <p className="num text-xl font-semibold">{result.sma.value?.toFixed(2) ?? "—"}</p>
            <p className={cn(
              "text-[10px]",
              result.sma.signal === "above_sma" && "text-gain",
              result.sma.signal === "below_sma" && "text-loss",
            )}>
              price {result.sma.signal?.replace("_", " ") ?? "—"}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function DividendSection({ result }: { result: DividendResult }) {
  if (result.error || !result.yield) {
    return null; // Many tickers don't pay dividends — silent skip.
  }
  const yld = (result.yield ?? 0) * (result.yield && result.yield < 1 ? 100 : 1);
  return (
    <section className="card mb-3">
      <h3 className="text-sm font-semibold">Dividend</h3>
      <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-[10px] uppercase text-[hsl(var(--text-muted))]">Yield</p>
          <p className="num text-xl font-semibold text-gain">{yld.toFixed(2)}%</p>
        </div>
        {result.safety_score != null && (
          <div>
            <p className="text-[10px] uppercase text-[hsl(var(--text-muted))]">Safety</p>
            <p className="num text-xl font-semibold">{Math.round(result.safety_score)}/100</p>
          </div>
        )}
        {result.income_rating && (
          <div>
            <p className="text-[10px] uppercase text-[hsl(var(--text-muted))]">Rating</p>
            <p className="text-xl font-semibold capitalize">{result.income_rating}</p>
          </div>
        )}
      </div>
      {result.consecutive_increases != null && result.consecutive_increases > 0 && (
        <p className="mt-2 text-[11px] text-[hsl(var(--text-muted))]">
          {result.consecutive_increases} consecutive years of dividend increases
        </p>
      )}
    </section>
  );
}

function NewsSection({ articles }: { articles: NewsArticle[] }) {
  return (
    <section className="card">
      <h3 className="text-sm font-semibold">Latest news</h3>
      <ul className="mt-2 divide-y divide-[hsl(var(--border))]">
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
                <p className="mt-0.5 text-[10px] text-[hsl(var(--text-muted))]">
                  {a.source}{a.published_at ? ` · ${a.published_at.slice(0, 10)}` : ""}
                </p>
              </span>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--text-muted))] group-hover:text-accent" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
