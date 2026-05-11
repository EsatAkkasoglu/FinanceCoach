import { Plus, Trash2 } from "lucide-react";
import { formatCurrency } from "@/lib/format";

export interface HoldingDraft {
  ticker: string;
  quantity: number;
  costBasis: number;
  assetClass: "stock" | "crypto" | "cash" | "etf";
}

interface Props {
  holdings: HoldingDraft[];
  onChange: (holdings: HoldingDraft[]) => void;
}

const EMPTY: HoldingDraft = { ticker: "", quantity: 0, costBasis: 0, assetClass: "stock" };

export function StepPortfolio({ holdings, onChange }: Props) {
  const update = (i: number, patch: Partial<HoldingDraft>) =>
    onChange(holdings.map((h, idx) => (idx === i ? { ...h, ...patch } : h)));
  const remove = (i: number) => onChange(holdings.filter((_, idx) => idx !== i));
  const add = () => onChange([...holdings, { ...EMPTY }]);

  const total = holdings.reduce((sum, h) => sum + h.quantity * h.costBasis, 0);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Starting portfolio</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          Add what you already hold, or skip and add later from the Portfolio tab.
        </p>
      </div>

      {holdings.length === 0 && (
        <div className="rounded-lg border border-dashed border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--text-muted))]">
          No holdings yet. You can always come back to this.
        </div>
      )}

      <div className="space-y-3">
        {holdings.map((h, i) => (
          <div
            key={i}
            className="flex items-center gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3"
          >
            <input
              value={h.ticker}
              onChange={(e) => update(i, { ticker: e.target.value.toUpperCase() })}
              placeholder="NVDA"
              className="num w-0 min-w-0 flex-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <input
              type="number"
              step="any"
              value={h.quantity || ""}
              onChange={(e) => update(i, { quantity: Number(e.target.value) })}
              placeholder="qty"
              className="num w-20 shrink-0 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <input
              type="number"
              step="any"
              value={h.costBasis || ""}
              onChange={(e) => update(i, { costBasis: Number(e.target.value) })}
              placeholder="cost"
              className="num w-24 shrink-0 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <select
              value={h.assetClass}
              onChange={(e) => update(i, { assetClass: e.target.value as HoldingDraft["assetClass"] })}
              className="w-24 shrink-0 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-1.5 text-sm outline-none"
            >
              <option value="stock">Stock</option>
              <option value="crypto">Crypto</option>
              <option value="etf">ETF</option>
              <option value="cash">Cash</option>
            </select>
            <button
              type="button"
              onClick={() => remove(i)}
              className="shrink-0 rounded-md p-2 text-[hsl(var(--text-muted))] hover:text-loss"
              aria-label="Remove"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={add}
        className="flex items-center gap-2 rounded-md border border-dashed border-[hsl(var(--border))] px-3 py-2 text-sm text-[hsl(var(--text-muted))] hover:border-accent hover:text-accent"
      >
        <Plus className="h-4 w-4" />
        Add holding
      </button>

      {total > 0 && (
        <div className="text-right text-sm text-[hsl(var(--text-muted))]">
          Estimated total cost: <span className="num text-[hsl(var(--text))]">{formatCurrency(total)}</span>
        </div>
      )}
    </div>
  );
}
