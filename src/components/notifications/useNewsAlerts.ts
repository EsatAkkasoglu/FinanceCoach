/**
 * useNewsAlerts — polls the backend for proactive news alerts and surfaces new
 * ones as a toast. The architecture is pull-based (no push/SSE for news), so we
 * poll on an interval, but pause while the tab is hidden to avoid waste and
 * resume immediately on focus. The first load never toasts (it would fire for a
 * backlog); only alerts unseen in a previous poll raise a toast.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { getNewsAlerts, markAlertsRead, type NewsAlert } from "@/lib/api";

const POLL_MS = 45_000;

export interface UseNewsAlerts {
  alerts: NewsAlert[];
  unreadCount: number;
  loading: boolean;
  refresh: () => void;
  markRead: (ids?: number[]) => Promise<void>;
}

export function useNewsAlerts(): UseNewsAlerts {
  const { t } = useTranslation("notifications");
  const [alerts, setAlerts] = useState<NewsAlert[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const knownIds = useRef<Set<number>>(new Set());
  const primed = useRef(false); // first successful poll seeds knownIds silently
  const inFlight = useRef(false);

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const res = await getNewsAlerts({ limit: 30 });
      setAlerts(res.items);
      setUnreadCount(res.unread_count);

      if (primed.current) {
        const fresh = res.items.filter((a) => !a.read && !knownIds.current.has(a.id));
        if (fresh.length === 1 && fresh[0].article) {
          toast.info(t("toast.single", { title: fresh[0].article.title }));
        } else if (fresh.length > 1) {
          toast.info(t("toast.many", { count: fresh.length }));
        }
      }
      for (const a of res.items) knownIds.current.add(a.id);
      primed.current = true;
    } catch {
      // best-effort — a failed poll just leaves the last good state
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, [t]);

  const markRead = useCallback(
    async (ids?: number[]) => {
      await markAlertsRead(ids);
      // Optimistic local update so the badge reacts immediately.
      setAlerts((prev) =>
        prev.map((a) => (!ids || ids.includes(a.id) ? { ...a, read: true } : a)),
      );
      setUnreadCount((c) => {
        if (!ids) return 0;
        const newlyRead = alerts.filter((a) => ids.includes(a.id) && !a.read).length;
        return Math.max(0, c - newlyRead);
      });
    },
    [alerts],
  );

  useEffect(() => {
    void poll();
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer) return;
      timer = setInterval(() => void poll(), POLL_MS);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        void poll(); // catch up immediately on focus
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [poll]);

  return { alerts, unreadCount, loading, refresh: () => void poll(), markRead };
}
