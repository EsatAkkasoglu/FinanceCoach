import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput, Select } from "@/components/ui/Field";
import {
  addHolding,
  resolveSymbol,
  updateHolding,
  type Holding,
  type HoldingInput,
  type SymbolSuggestion,
} from "@/lib/api";

const ASSET_OPTIONS = [
  { value: "stock", label: "Stock" },
  { value: "etf", label: "ETF" },
  { value: "crypto", label: "Crypto" },
  { value: "bond", label: "Bond" },
  { value: "fund", label: "Fund (TEFAS)" },
  { value: "cash", label: "Cash" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  /** When set, the modal runs in edit mode and prefills from the holding. */
  editing?: Holding | null;
}

const EMPTY: HoldingInput = {
  ticker: "",
  quantity: 0,
  cost_basis: 0,
  asset_class: "stock",
};

const ASSET_CLASS_FROM_SUGGESTION: Record<string, HoldingInput["asset_class"]> = {
  crypto: "crypto",
  equity: "stock",
  stock: "stock",
  etf: "etf",
  bond: "bond",
  bond_yield: "bond",
  fund: "fund",
};

export function HoldingFormModal({ open, onClose, onSaved, editing }: Props) {
  const isEdit = Boolean(editing?.id);
  const [form, setForm] = useState<HoldingInput>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof HoldingInput, string>>>({});
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const justPickedRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        ticker: editing.ticker,
        quantity: editing.quantity,
        cost_basis: editing.cost_basis,
        asset_class: editing.asset_class,
      });
    } else {
      setForm(EMPTY);
    }
    setErrors({});
    setSuggestions([]);
    setShowSuggestions(false);
  }, [open, editing]);

  function onTickerChange(rawValue: string) {
    const value = rawValue.toUpperCase();
    setForm((f) => ({ ...f, ticker: value }));
    if (justPickedRef.current) {
      justPickedRef.current = false;
      return;
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (value.trim().length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    debounceRef.current = window.setTimeout(async () => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setSuggestLoading(true);
      try {
        const results = await resolveSymbol(value, 8);
        setSuggestions(results);
        setShowSuggestions(results.length > 0);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      } finally {
        setSuggestLoading(false);
      }
    }, 250);
  }

  function pickSuggestion(s: SymbolSuggestion) {
    justPickedRef.current = true;
    setForm((f) => ({
      ...f,
      ticker: s.ticker,
      asset_class: ASSET_CLASS_FROM_SUGGESTION[s.asset_class] ?? f.asset_class,
    }));
    setShowSuggestions(false);
  }

  function validate(): boolean {
    const next: typeof errors = {};
    if (!form.ticker.trim()) next.ticker = "Required";
    if (!(form.quantity > 0)) next.quantity = "Must be greater than 0";
    if (form.cost_basis < 0) next.cost_basis = "Cannot be negative";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    try {
      if (isEdit && editing?.id != null) {
        await updateHolding(editing.id, form);
        toast.success(`${form.ticker.toUpperCase()} updated`);
      } else {
        await addHolding(form);
        toast.success(`${form.ticker.toUpperCase()} added`);
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error((err as Error).message || "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit holding" : "Add a holding"}
      description={isEdit ? "Update the position details." : "Enter what you own. Prices come from live market data."}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">Cancel</Button>
          <Button onClick={handleSubmit} loading={submitting} type="submit">
            {isEdit ? "Save changes" : "Add holding"}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="Ticker" hint="Type a name or symbol — we'll suggest matches" error={errors.ticker}>
          <div className="relative">
            <TextInput
              autoFocus
              value={form.ticker}
              onChange={(e) => onTickerChange(e.target.value)}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              onBlur={() => window.setTimeout(() => setShowSuggestions(false), 120)}
              placeholder="AAPL · Apple · BTC"
              spellCheck={false}
              autoComplete="off"
            />
            {showSuggestions && (
              <div className="absolute left-0 right-0 top-full mt-1 z-50 max-h-72 overflow-y-auto rounded-lg border border-white/10 bg-zinc-900/95 shadow-xl backdrop-blur">
                {suggestLoading && suggestions.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-zinc-400">Searching…</div>
                ) : suggestions.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-zinc-400">No matches</div>
                ) : (
                  suggestions.map((s) => (
                    <button
                      key={`${s.source}-${s.ticker}`}
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pickSuggestion(s)}
                      className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-white/5"
                    >
                      <span className="flex flex-col">
                        <span className="font-mono font-semibold text-emerald-300">{s.ticker}</span>
                        <span className="text-xs text-zinc-400 truncate max-w-[20rem]">{s.description}</span>
                      </span>
                      <span className="text-overline uppercase text-zinc-500">
                        {s.asset_class}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={errors.quantity}>
            <TextInput
              inputMode="decimal"
              value={form.quantity || ""}
              onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) || 0 })}
              placeholder="10"
            />
          </Field>
          <Field label="Avg cost / unit" hint="Optional" error={errors.cost_basis}>
            <TextInput
              inputMode="decimal"
              value={form.cost_basis || ""}
              onChange={(e) => setForm({ ...form, cost_basis: Number(e.target.value) || 0 })}
              placeholder="150.50"
            />
          </Field>
        </div>

        <Field label="Asset class">
          <Select
            options={ASSET_OPTIONS}
            value={form.asset_class}
            onChange={(e) => setForm({ ...form, asset_class: e.target.value as HoldingInput["asset_class"] })}
          />
        </Field>

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
