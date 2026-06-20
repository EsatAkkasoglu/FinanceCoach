/**
 * NotificationBell — the proactive news-alert surface in the app header.
 *
 * A bell with an unread badge; clicking opens a popover listing alerts. Each
 * alert turns a matched headline into action: an "Ask the coach" CTA deep-links
 * to the chat with a pre-filled prompt (via ?ask=) so the user can decide
 * whether to take a position, plus a direct link to the source article.
 *
 * News is pull-based, so freshness comes from useNewsAlerts' polling; this
 * component is purely presentational over that hook.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Bell, ExternalLink, MessageSquare, TrendingDown, TrendingUp, Minus } from "lucide-react";

import { buildLocalizedPath, getLanguageFromPath } from "@/lib/routing";
import { cn } from "@/lib/cn";
import { type NewsAlert } from "@/lib/api";
import { useNewsAlerts } from "./useNewsAlerts";

const SENTIMENT = {
  positive: { cls: "bg-gain/10 text-gain", Icon: TrendingUp },
  neutral: { cls: "bg-surface-raised text-content-muted", Icon: Minus },
  negative: { cls: "bg-loss/10 text-loss", Icon: TrendingDown },
} as const;

export function NotificationBell() {
  const { t } = useTranslation("notifications");

  const reasonLabel = (reason: string): string => {
    if (reason.startsWith("watchlist:")) return t("reason.watchlist", { value: reason.slice(10) });
    if (reason.startsWith("category:")) return t("reason.category", { value: reason.slice(9) });
    if (reason === "sentiment") return t("reason.sentiment");
    return t("reason.generic");
  };
  const navigate = useNavigate();
  const location = useLocation();
  const reduce = useReducedMotion();
  const { alerts, unreadCount, markRead } = useNewsAlerts();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const lang = getLanguageFromPath(location.pathname) ?? "en";

  function askCoach(alert: NewsAlert) {
    if (!alert.article) return;
    const prompt = t("askPrompt", { source: alert.article.source, title: alert.article.title });
    void markRead([alert.id]);
    setOpen(false);
    navigate(`${buildLocalizedPath(lang, "/chat")}?ask=${encodeURIComponent(prompt)}`);
  }

  return (
    <div ref={rootRef} className="relative flex items-center">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("bell.label")}
        title={unreadCount > 0 ? t("bell.unreadCount", { count: unreadCount }) : t("bell.label")}
        className="relative flex h-8 w-8 items-center justify-center rounded-lg text-[hsl(var(--text-muted))] transition hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[1rem] items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-white tabular-nums">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className="absolute right-0 top-full z-50 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] shadow-xl"
          >
            <div className="flex items-center gap-2 border-b border-[hsl(var(--border))]/60 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{t("title")}</p>
                <p className="truncate text-caption text-content-muted">{t("subtitle")}</p>
              </div>
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={() => void markRead()}
                  className="ml-auto shrink-0 rounded-lg px-2 py-1 text-caption text-accent transition hover:bg-[hsl(var(--surface-2))]"
                >
                  {t("markAllRead")}
                </button>
              )}
            </div>

            <div className="max-h-[26rem] overflow-y-auto">
              {alerts.length === 0 ? (
                <p className="px-4 py-6 text-sm text-content-muted">{t("empty")}</p>
              ) : (
                <ul className="divide-y divide-[hsl(var(--border))]/50">
                  {alerts.map((a) => {
                    const art = a.article;
                    const s = (art?.sentiment && art.sentiment in SENTIMENT
                      ? art.sentiment
                      : "neutral") as keyof typeof SENTIMENT;
                    const cfg = SENTIMENT[s];
                    return (
                      <li
                        key={a.id}
                        className={cn(
                          "px-4 py-3 transition-colors",
                          a.read ? "opacity-70" : "bg-accent/[0.03]",
                        )}
                      >
                        <div className="flex items-start gap-2.5">
                          <span
                            className={cn(
                              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                              cfg.cls,
                            )}
                          >
                            <cfg.Icon className="h-3 w-3" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-caption font-medium uppercase tracking-wide text-accent/80">
                              {reasonLabel(a.reason)}
                            </p>
                            <p className="mt-0.5 line-clamp-2 text-sm text-content">
                              {art?.summary || art?.title}
                            </p>
                            {art && (
                              <p className="mt-0.5 truncate text-caption text-content-muted">{art.source}</p>
                            )}
                            <div className="mt-2 flex items-center gap-3">
                              <button
                                type="button"
                                onClick={() => askCoach(a)}
                                className="inline-flex items-center gap-1 rounded-lg bg-accent/10 px-2 py-1 text-caption font-medium text-accent transition hover:bg-accent/20"
                              >
                                <MessageSquare className="h-3 w-3" />
                                {t("askCoach")}
                              </button>
                              {art && (
                                <a
                                  href={art.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={() => void markRead([a.id])}
                                  className="inline-flex items-center gap-1 text-caption text-content-muted transition hover:text-content"
                                >
                                  <ExternalLink className="h-3 w-3" />
                                  {t("viewArticle")}
                                </a>
                              )}
                            </div>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
