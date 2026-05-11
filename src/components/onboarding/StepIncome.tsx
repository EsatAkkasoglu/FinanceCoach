import { formatCurrency } from "@/lib/format";

interface Props {
  monthlyIncome: number;
  spendingPace: number;
  onChange: (patch: { monthlyIncome?: number; spendingPace?: number }) => void;
}

const PACE_LABELS = ["Saver", "Frugal", "Balanced", "Spender", "YOLO"];

export function StepIncome({ monthlyIncome, spendingPace, onChange }: Props) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">A bit about your cash flow</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          So I can ground budget advice in real numbers. Stays on your device.
        </p>
      </div>

      <label className="block">
        <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
          Monthly take-home (USD)
        </span>
        <input
          type="number"
          min={0}
          step={500}
          value={monthlyIncome || ""}
          onChange={(e) => onChange({ monthlyIncome: Number(e.target.value) })}
          placeholder="7500"
          className="num mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
        />
        <span className="mt-1 block text-xs text-[hsl(var(--text-muted))]">
          {monthlyIncome > 0 ? `${formatCurrency(monthlyIncome)} per month` : "Just a ballpark"}
        </span>
      </label>

      <div>
        <div className="flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
            Spending pace
          </span>
          <span className="text-sm font-medium text-accent">{PACE_LABELS[spendingPace - 1]}</span>
        </div>
        <input
          type="range"
          min={1}
          max={5}
          step={1}
          value={spendingPace}
          onChange={(e) => onChange({ spendingPace: Number(e.target.value) })}
          className="mt-3 w-full accent-[#1FB57A]"
        />
        <div className="mt-1 flex justify-between text-[10px] text-[hsl(var(--text-muted))]">
          {PACE_LABELS.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
