/**
 * FX rates hook — fetches conversion rates for a chosen base currency.
 *
 * Math model: the backend returns `rates[X]` = how many units of X equal 1 unit
 * of `base`. So to convert `amount` from currency `fromCcy` to `base`, divide by
 * `rates[fromCcy]`. To then express in any target currency `T`, multiply by
 * `rates[T]`. Since the hook is keyed by `target` (we re-fetch with base=target),
 * `convert(amount, fromCcy)` returns the value in `target` directly.
 */
import { useEffect, useRef, useState } from "react";
import { getFxRates, type FxRates } from "@/lib/api";
import { useSettingsStore, type DisplayCurrency } from "@/store";

const TTL_MS = 15 * 60 * 1000;

interface CacheEntry {
  rates: FxRates;
  fetchedAt: number;
}

const moduleCache: Map<string, CacheEntry> = new Map();
const inflight: Map<string, Promise<FxRates>> = new Map();

export function clearFxCache(base?: string) {
  if (base) moduleCache.delete(base);
  else moduleCache.clear();
}

export async function fetchFxRates(base: string, force = false): Promise<FxRates> {
  const now = Date.now();
  const cached = moduleCache.get(base);
  if (!force && cached && now - cached.fetchedAt < TTL_MS) return cached.rates;

  if (force) inflight.delete(base);
  const pending = inflight.get(base);
  if (pending) return pending;

  const p = getFxRates(base).then((rates) => {
    moduleCache.set(base, { rates, fetchedAt: Date.now() });
    inflight.delete(base);
    return rates;
  }).catch((err) => {
    inflight.delete(base);
    throw err;
  });
  inflight.set(base, p);
  return p;
}

export interface UseFxRates {
  rates: FxRates | null;
  loading: boolean;
  error: string | null;
  /** The currency that `convert` / `convertBag` produce values in. */
  target: DisplayCurrency;
  /** Convert `amount` from `fromCcy` into the currently selected target. */
  convert: (amount: number, fromCcy: string) => number | null;
  /** Collapse a per-currency dict into a single number in the selected target. */
  convertBag: (bag: Record<string, number>) => number | null;
  /** Force-refresh rates from the server, bypassing cache. */
  refresh: () => void;
}

export function useFxRates(): UseFxRates {
  const target = useSettingsStore((s) => s.displayCurrency);
  const [rates, setRates] = useState<FxRates | null>(() => moduleCache.get(target)?.rates ?? null);
  const [loading, setLoading] = useState(!rates);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);
  const [forceCount, setForceCount] = useState(0);

  useEffect(() => {
    const my = ++reqId.current;
    const force = forceCount > 0;
    if (force) clearFxCache(target);
    const cached = moduleCache.get(target);
    if (!force && cached) {
      setRates(cached.rates);
      setError(null);
    }
    setLoading(true);
    fetchFxRates(target, force)
      .then((r) => {
        if (my !== reqId.current) return;
        setRates(r);
        setError(null);
      })
      .catch((e: Error) => {
        if (my !== reqId.current) return;
        setError(e.message);
      })
      .finally(() => {
        if (my !== reqId.current) return;
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, forceCount]);

  function refresh() { setForceCount((n) => n + 1); }

  function convert(amount: number, fromCcy: string): number | null {
    if (!rates) return null;
    const from = fromCcy.toUpperCase();
    if (from === rates.base) return amount;
    const rate = rates.rates[from];
    if (!rate || rate <= 0) return null;
    // rates[from] is "how many `from` per 1 `base`" → divide to get base-equiv.
    return amount / rate;
  }

  function convertBag(bag: Record<string, number>): number | null {
    if (!rates) return null;
    let total = 0;
    let anyMissing = false;
    for (const [ccy, amount] of Object.entries(bag)) {
      const v = convert(amount, ccy);
      if (v == null) anyMissing = true;
      else total += v;
    }
    if (anyMissing && total === 0) return null;
    return total;
  }

  return { rates, loading, error, convert, convertBag, target, refresh };
}

export const SUPPORTED_CURRENCIES: DisplayCurrency[] = ["TRY", "USD", "EUR"];
