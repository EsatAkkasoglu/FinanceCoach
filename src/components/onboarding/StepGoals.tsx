import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import {
  GOAL_TYPES,
  FINANCIAL_CHALLENGES,
  type GoalTypeId,
  type FinancialChallengeId,
} from "./data";

export interface GoalDraft {
  type: GoalTypeId;
  title: string;
  amount: number;
  targetDate: string; // YYYY-MM-DD
}

interface Props {
  goal: GoalDraft;
  financialChallenges: FinancialChallengeId[];
  onChange: (patch: {
    goal?: Partial<GoalDraft>;
    financialChallenges?: FinancialChallengeId[];
  }) => void;
}

export function StepGoals({ goal, financialChallenges, onChange }: Props) {
  const { t } = useTranslation("onboarding");
  const selected = GOAL_TYPES.find((g) => g.id === goal.type);

  function toggleChallenge(id: FinancialChallengeId) {
    const next = financialChallenges.includes(id)
      ? financialChallenges.filter((c) => c !== id)
      : [...financialChallenges, id];
    onChange({ financialChallenges: next });
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{t("goals.title")}</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">{t("goals.subtitle")}</p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {GOAL_TYPES.map((g) => (
          <button
            key={g.id}
            type="button"
            onClick={() =>
              onChange({
                goal: {
                  type: g.id,
                  title: t(`goals.types.${g.id}`),
                },
              })
            }
            className={cn(
              "flex flex-col items-center gap-1 rounded-lg border p-4 transition",
              goal.type === g.id
                ? "border-accent bg-accent-muted shadow-glow"
                : "border-[hsl(var(--border))] hover:border-accent"
            )}
          >
            <span className="text-3xl">{g.emoji}</span>
            <span className="text-xs">{t(`goals.types.${g.id}`)}</span>
          </button>
        ))}
      </div>

      {selected && (
        <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4">
          <label className="block">
            <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              {t("goals.targetAmount")}
            </span>
            <input
              type="number"
              min={0}
              step={1000}
              value={goal.amount || ""}
              onChange={(e) => onChange({ goal: { amount: Number(e.target.value) } })}
              placeholder="300000"
              className="num mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
            />
            <span className="mt-1 block text-xs text-[hsl(var(--text-muted))]">
              {goal.amount > 0 ? formatCurrency(goal.amount) : t("goals.numbersOnly")}
            </span>
          </label>

          <label className="block">
            <span className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              {t("goals.byWhen")}
            </span>
            <input
              type="date"
              value={goal.targetDate}
              onChange={(e) => onChange({ goal: { targetDate: e.target.value } })}
              className="mt-2 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] px-4 py-3 text-base outline-none focus:border-accent"
            />
          </label>
        </div>
      )}

      <div className="space-y-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
            {t("goals.familiar")}
          </p>
          <p className="mt-0.5 text-sm text-[hsl(var(--text-muted))]">{t("goals.familiarHint")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {FINANCIAL_CHALLENGES.map((ch) => {
            const active = financialChallenges.includes(ch.id as FinancialChallengeId);
            return (
              <button
                key={ch.id}
                type="button"
                onClick={() => toggleChallenge(ch.id as FinancialChallengeId)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition",
                  active
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:border-accent/50"
                )}
              >
                <span>{ch.emoji}</span>
                {t(`goals.challenges.${ch.id}`)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
