/**
 * WatchlistManager — add/remove the symbols and keywords that drive proactive
 * news alerts. Symbols are matched against article tickers; keywords against the
 * headline/snippet (see backend services/news_alerts.py). Lives in Settings →
 * Behaviour, the semantic home for "what should alert me".
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Plus, X, Hash, Tag } from "lucide-react";

import {
  addWatchlistItem,
  listWatchlist,
  removeWatchlistItem,
  type WatchKind,
  type WatchlistItem,
} from "@/lib/api";
import { cn } from "@/lib/cn";

export function WatchlistManager() {
  const { t } = useTranslation("notifications");
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [kind, setKind] = useState<WatchKind>("symbol");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listWatchlist().then((rows) => { if (!cancelled) setItems(rows); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  async function add() {
    const v = value.trim();
    if (!v || busy) return;
    setBusy(true);
    try {
      const created = await addWatchlistItem(kind, v);
      if (!created) {
        toast.error(t("watchlist.addError"));
        return;
      }
      setItems((prev) => (prev.some((i) => i.id === created.id) ? prev : [...prev, created]));
      setValue("");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    const ok = await removeWatchlistItem(id);
    if (ok) setItems((prev) => prev.filter((i) => i.id !== id));
  }

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <p className="text-sm font-medium">{t("watchlist.title")}</p>
      </div>
      <p className="mb-3 text-xs text-content-muted">{t("watchlist.subtitle")}</p>

      {/* Kind toggle */}
      <div className="mb-2 flex gap-2">
        {(["symbol", "keyword"] as const).map((k) => {
          const Icon = k === "symbol" ? Hash : Tag;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition",
                kind === k
                  ? "border-accent bg-accent-muted text-accent"
                  : "border-line text-content-muted hover:text-content",
              )}
            >
              <Icon className="h-3 w-3" />
              {t(k === "symbol" ? "watchlist.kindSymbol" : "watchlist.kindKeyword")}
            </button>
          );
        })}
      </div>

      {/* Add row */}
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void add(); } }}
          placeholder={t(kind === "symbol" ? "watchlist.symbolPlaceholder" : "watchlist.keywordPlaceholder")}
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface-raised px-3 py-1.5 text-sm outline-none transition focus:border-accent"
        />
        <button
          type="button"
          onClick={() => void add()}
          disabled={busy || !value.trim()}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("watchlist.add")}
        </button>
      </div>

      {/* Chips */}
      <div className="mt-3">
        {items.length === 0 ? (
          <p className="text-xs text-content-muted">{t("watchlist.empty")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {items.map((it) => (
              <li
                key={it.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-raised px-2.5 py-1 text-xs"
              >
                {it.kind === "symbol" ? (
                  <Hash className="h-3 w-3 text-accent/70" />
                ) : (
                  <Tag className="h-3 w-3 text-content-muted" />
                )}
                <span className="font-medium">{it.value}</span>
                <button
                  type="button"
                  onClick={() => void remove(it.id)}
                  aria-label={t("watchlist.remove")}
                  className="rounded-full p-0.5 text-content-muted transition hover:bg-loss/10 hover:text-loss"
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
