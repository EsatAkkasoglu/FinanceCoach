/**
 * NewsPanel — market headlines pre-collected & sentiment-tagged by the backend
 * news collector. Self-contained: fetches its own data from /news/feed (cheap,
 * DB-backed) rather than riding the dashboard's portfolio cache, since news is
 * independent of holdings. Degrades to an empty state when the collector hasn't
 * run yet (e.g. a fresh DB or a Cloud Run instance awaiting its first poll).
 *
 * Animation: the card shell uses framer-motion (matching the rest of the
 * dashboard); the headline list reveal is done with anime.js v4 (createScope +
 * stagger) and the count chip with an anime.js count-up — the two libraries
 * coexist, each used where it reads best.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { motion, useReducedMotion } from "framer-motion";
import { Newspaper, ExternalLink, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { animate, createScope, stagger, utils } from "animejs";

import { getNewsFeed, type NewsItem } from "@/lib/api";
import { AnimatedNumber } from "@/components/ui/AnimatedNumber";
import { cn } from "@/lib/cn";

const CARD_VAR = {
  hidden: { opacity: 0, y: 18, scale: 0.99 },
  visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.38, ease: [0.4, 0, 0.2, 1] } },
};

// Static sentiment config (literal keys keep react-i18next strict typing happy).
const SENTIMENT = {
  positive: { cls: "bg-gain/10 text-gain", Icon: TrendingUp },
  neutral: { cls: "bg-surface-raised text-content-muted", Icon: Minus },
  negative: { cls: "bg-loss/10 text-loss", Icon: TrendingDown },
} as const;

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor((Date.now() - then) / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

export function NewsPanel({ span = "md:col-span-2 lg:col-span-12", limit = 6 }: {
  span?: string;
  limit?: number;
}) {
  const { t } = useTranslation("dashboard");
  const [items, setItems] = useState<NewsItem[] | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    let cancelled = false;
    getNewsFeed({ limit })
      .then((rows) => { if (!cancelled) setItems(rows); })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [limit]);

  // anime.js v4 staggered reveal of the headline rows. createScope binds the
  // selectors to this list and auto-reverts inline styles on cleanup; running
  // in a layout effect sets the start state before paint (no flash). Re-runs
  // whenever the items change (e.g. after the async fetch resolves).
  useLayoutEffect(() => {
    if (!listRef.current || !items || items.length === 0) return;
    const scope = createScope({ root: listRef.current }).add(() => {
      if (reduce) {
        utils.set(".news-item", { opacity: 1, translateY: 0 });
        return;
      }
      animate(".news-item", {
        opacity: [0, 1],
        translateY: [10, 0],
        delay: stagger(55),
        duration: 440,
        ease: "outQuad",
      });
    });
    return () => scope.revert();
  }, [items, reduce]);

  const loading = items === null;

  const SENTIMENT_LABEL: Record<keyof typeof SENTIMENT, string> = {
    positive: t("news.sentiment.positive"),
    neutral: t("news.sentiment.neutral"),
    negative: t("news.sentiment.negative"),
  };

  return (
    <motion.div variants={CARD_VAR} className={cn("card card-hover flex flex-col", span)}>
      <div className="flex items-center gap-1.5">
        <Newspaper className="h-4 w-4 shrink-0 text-content-muted" />
        <span className="text-overline uppercase text-content-muted">{t("news.title")}</span>
        {!loading && items.length > 0 && (
          <span className="ml-auto inline-flex items-center rounded-full bg-surface-raised px-2 py-0.5 text-caption tabular-nums text-content-muted">
            <AnimatedNumber value={items.length} duration={700} />
          </span>
        )}
      </div>

      {loading ? (
        <div className="mt-3 space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="animate-pulse rounded-lg bg-surface-raised h-10" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-content-muted">{t("news.empty")}</p>
      ) : (
        <ul ref={listRef} className="mt-3 space-y-1.5">
          {items.map((it) => {
            const s = (it.sentiment && it.sentiment in SENTIMENT ? it.sentiment : "neutral") as keyof typeof SENTIMENT;
            const cfg = SENTIMENT[s];
            return (
              <li key={it.id} className="news-item">
                <a
                  href={it.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-raised/50"
                >
                  <span className={cn("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full", cfg.cls)}>
                    <cfg.Icon className="h-3 w-3" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 text-sm text-content group-hover:text-accent">
                      {it.summary || it.title}
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-caption text-content-muted">
                      <span className="truncate">{it.source}</span>
                      {it.published_at && <span className="shrink-0">· {relativeTime(it.published_at)}</span>}
                      <span className="shrink-0 opacity-70">· {SENTIMENT_LABEL[s]}</span>
                    </span>
                  </span>
                  <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-content-muted opacity-0 transition-opacity group-hover:opacity-100" />
                </a>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-auto pt-3 text-caption text-content-muted">{t("news.source")}</div>
    </motion.div>
  );
}
