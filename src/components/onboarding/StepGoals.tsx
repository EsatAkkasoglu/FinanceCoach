import { GOAL_TYPES, type GoalTypeId } from "./data";
import { formatCurrency } from "@/lib/format";
import { cn } from "@/lib/cn";

export interface GoalDraft {
  type: GoalTypeId;
  title: string;
  amount: number;
  targetDate: string; // YYYY-MM-DD
}

interface Props {
  goal: GoalDraft;
  onChange: (patch: Partial<GoalDraft>) => void;
}

export function StepGoals({ goal, onChange }: Props) {
  const selected = GOAL_TYPES.find((g) => g.id === goal.type);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">What are you saving for?</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          Pick a primary goal — you can add more later.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {GOAL_TYPES.map((g) => (
          <button
            key={g.id}
            type="button"
            onClick={() => onChange({ type: g.id, title: g.label })}
            className={cn(
              "flex flex-col items-center gap-1 rounded-lg border p-4 transition",
              goal.type === g.id
                ? "border-accent bg-accent-muted shadow-glow"
                : "border-[hsl(var(--border))] hover:border-accent"
            )}
          >
            <span className="text-3xl">{g.emoji}</span>
            <span className="text-xs">{g.label}</span>
          </button>
        ))}
      </div>

      {selected && (
        <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4">
          <label className="block">
            <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              Target amount
            </span>
            <input
              type="number"
              min={0}
              step={1000}
              value={goal.amount || ""}
              onChange={(e) => onChange({ amount: Number(e.target.value) })}
              placeholder="300000"
              className="num mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
            />
            <span className="mt-1 block text-xs text-[hsl(var(--text-muted))]">
              {goal.amount > 0 ? formatCurrency(goal.amount) : "Numbers only"}
            </span>
          </label>

          <label className="block">
            <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              By when?
            </span>
            <input
              type="date"
              value={goal.targetDate}
              onChange={(e) => onChange({ targetDate: e.target.value })}
              className="mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
            />
          </label>
        </div>
      )}
    </div>
  );
}
