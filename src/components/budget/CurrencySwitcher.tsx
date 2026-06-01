import { useEffect, useRef, useState } from "react";
import { Globe, Loader2, RefreshCw, ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { useSettingsStore, type DisplayCurrency } from "@/store";
import { SUPPORTED_CURRENCIES, useFxRates, clearFxCache } from "@/lib/fx";

const SYMBOLS: Record<DisplayCurrency, string> = {
  TRY: "₺",
  USD: "$",
  EUR: "€",
};

export function CurrencySwitcher({
  className,
  variant = "full",
}: {
  className?: string;
  /** "full" — inline segmented control (Settings). "compact" — header dropdown. */
  variant?: "full" | "compact";
}) {
  const current = useSettingsStore((s) => s.displayCurrency);
  const setCurrent = useSettingsStore((s) => s.setDisplayCurrency);
  const { rates, loading, error, refresh } = useFxRates();
  const [ageLabel, setAgeLabel] = useState<string>("");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

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

  // Close the compact dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function handleSelect(c: DisplayCurrency) {
    clearFxCache(c);
    setCurrent(c);
  }

  const ratesNote = error ? (
    <span className="text-warning">offline</span>
  ) : ageLabel ? (
    <span className="flex items-center gap-1"><Globe className="h-3 w-3" /> {ageLabel}</span>
  ) : null;

  // ── Compact: single pill + dropdown (header) ──────────────────────────────
  if (variant === "compact") {
    return (
      <div ref={wrapRef} className={cn("relative", className)}>
        <button
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Display currency"
          className="flex items-center gap-1 rounded-full border border-line bg-surface-raised px-2.5 py-1 text-xs font-medium text-content transition hover:border-content-muted"
        >
          <span className="opacity-80">{SYMBOLS[current]}</span>
          {current}
          <ChevronDown className={cn("h-3 w-3 text-content-muted transition-transform", open && "rotate-180")} />
        </button>
        {open && (
          <div
            role="listbox"
            className="absolute right-0 top-full z-50 mt-1.5 w-40 rounded-lg border border-line bg-surface p-1 shadow-xl"
          >
            {SUPPORTED_CURRENCIES.map((c) => (
              <button
                key={c}
                role="option"
                aria-selected={current === c}
                onClick={() => { handleSelect(c); setOpen(false); }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition",
                  current === c ? "bg-accent-muted text-accent" : "text-content-muted hover:bg-surface-raised hover:text-content",
                )}
              >
                <span className="w-4 text-center opacity-80">{SYMBOLS[c]}</span>
                <span className="flex-1 text-left font-medium">{c}</span>
                {current === c && <Check className="h-3 w-3" />}
              </button>
            ))}
            <div className="mt-1 flex items-center justify-between border-t border-line px-2.5 pt-1.5 text-[10px] text-content-muted">
              {ratesNote ?? <span>—</span>}
              <button
                onClick={refresh}
                disabled={loading}
                title="Refresh rates"
                className="flex items-center gap-1 transition hover:text-content disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Full: inline segmented control (Settings) ─────────────────────────────
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
        title="Refresh rates"
        className="flex items-center gap-1 rounded-full border border-line bg-surface-raised px-2 py-1 text-[10px] text-content-muted transition hover:text-content disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        {ratesNote}
      </button>
    </div>
  );
}
