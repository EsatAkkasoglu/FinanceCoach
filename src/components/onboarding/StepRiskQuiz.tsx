import { RISK_QUIZ, scoreToLabel } from "./data";
import { cn } from "@/lib/cn";

interface Props {
  answers: Record<string, number>; // questionId → points
  onChange: (questionId: string, points: number) => void;
}

const LABEL_COLOR: Record<string, string> = {
  conservative: "text-blue-400",
  balanced: "text-accent",
  aggressive: "text-orange-400",
};

export function StepRiskQuiz({ answers, onChange }: Props) {
  const score = Object.values(answers).reduce((a, b) => a + b, 0);
  const label = scoreToLabel(score);
  const completed = Object.keys(answers).length;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Risk profile</h2>
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">
          5 quick questions. Your answers shape every recommendation.
        </p>
        <div className="mt-2 text-xs text-[hsl(var(--text-muted))]">
          {completed}/{RISK_QUIZ.length} answered ·{" "}
          <span className={cn("font-semibold", LABEL_COLOR[label])}>
            {completed === RISK_QUIZ.length ? `${label} (${score}/125)` : "in progress"}
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {RISK_QUIZ.map((q, idx) => (
          <div
            key={q.id}
            className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-4"
          >
            <div className="mb-3 text-sm font-medium">
              <span className="mr-2 text-[hsl(var(--text-muted))]">{idx + 1}.</span>
              {q.prompt}
            </div>
            <div className="grid gap-2">
              {q.options.map((o) => {
                const active = answers[q.id] === o.points;
                return (
                  <button
                    key={o.label}
                    type="button"
                    onClick={() => onChange(q.id, o.points)}
                    className={cn(
                      "rounded-md border px-3 py-2 text-left text-sm transition",
                      active
                        ? "border-accent bg-accent-muted"
                        : "border-[hsl(var(--border))] hover:border-accent"
                    )}
                  >
                    {o.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
