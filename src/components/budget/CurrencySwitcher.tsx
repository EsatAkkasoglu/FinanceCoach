import { useEffect, useState } from "react";
import { Globe, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { useSettingsStore, type DisplayCurrency } from "@/store";
import { SUPPORTED_CURRENCIES, useFxRates, clearFxCache } from "@/lib/fx";

const SYMBOLS: Record<DisplayCurrency, string> = {
  TRY: "₺",
  USD: "$",
  EUR: "€",
};

export function CurrencySwitcher({ className }: { className?: string }) {
  const current = useSettingsStore((s) => s.displayCurrency);
  const setCurrent = useSettingsStore((s) => s.setDisplayCurrency);
  const { rates, loading, error, refresh } = useFxRates();
  const [ageLabel, setAgeLabel] = useState<string>("");

  useEffect(() => {
    if (!rates) { setAgeLabel(""); return; }
    function tick() {
      const d = new Date(rates!.fetched_at * 1000);
      setAgeLabel(d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    }
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, [rates]);

  function handleSelect(c: DisplayCurrency) {
    clearFxCache(c);
    setCurrent(c);
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className="inline-flex items-center rounded-full border border-line bg-surface-raised p-0.5"
        role="group"
        aria-label="Display currency"
      >
        {SUPPORTED_CURRENCIES.map((c) => (
          <button
            key={c}
            onClick={() => handleSelect(c)}
            className={cn(
              "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition",
              current === c
                ? "bg-accent text-white"
                : "text-content-muted hover:text-content",
            )}
            aria-pressed={current === c}
          >
            <span className="opacity-80">{SYMBOLS[c]}</span>
            {c}
          </button>
        ))}
      </div>

      <button
        onClick={refresh}
        disabled={loading}
        title="Güncel kurları getir"
        className={cn(
          "flex items-center gap-1 rounded-full border border-line bg-surface-raised px-2 py-1 text-[10px] text-content-muted transition hover:text-content disabled:opacity-50",
        )}
      >
        {loading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <RefreshCw className="h-3 w-3" />
        )}
        {error ? (
          <span className="text-warning">offline</span>
        ) : ageLabel ? (
          <span className="flex items-center gap-0.5">
            <Globe className="h-3 w-3" /> {ageLabel}
          </span>
        ) : null}
      </button>
    </div>
  );
}
