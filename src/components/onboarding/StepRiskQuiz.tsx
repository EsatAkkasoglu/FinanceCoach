import { useTranslation } from "react-i18next";
import { RISK_QUIZ, scoreToLabel } from "./data";
import trOnboarding from "@/i18n/locales/tr/onboarding.json";
import enOnboarding from "@/i18n/locales/en/onboarding.json";
import { cn } from "@/lib/cn";

interface Props {
  answers: Record<string, number>;
  onChange: (questionId: string, points: number) => void;
}

const LABEL_COLOR: Record<string, string> = {
  conservative: "text-blue-400",
  balanced: "text-accent",
  aggressive: "text-orange-400",
};

type RiskTranslations = typeof trOnboarding;

export function StepRiskQuiz({ answers, onChange }: Props) {
  const { t, i18n } = useTranslation("onboarding");
  const riskTr = (i18n.language === "tr" ? trOnboarding : enOnboarding) as RiskTranslations;
  const score = Object.values(answers).reduce((a, b) => a + b, 0);
  const label = scoreToLabel(score);
  const completed = Object.keys(answers).length;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{t("risk.title")}</h2>
        <p className="mt-1 text-sm text-content-muted">{t("risk.subtitle")}</p>
        <div className="mt-2 text-xs text-content-muted">
          {t("risk.progress", { completed, total: RISK_QUIZ.length })} ·{" "}
          <span className={cn("font-semibold", LABEL_COLOR[label])}>
            {completed === RISK_QUIZ.length
              ? `${label} (${score}/125)`
              : t("risk.inProgress")}
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {RISK_QUIZ.map((q, idx) => {
          const qTr = riskTr.risk.questions[q.id as keyof typeof riskTr.risk.questions] as
            | { prompt: string; options: string[] }
            | undefined;
          const prompt = qTr?.prompt ?? q.prompt;
          const optionLabels: string[] = q.options.map((o, oi) => qTr?.options[oi] ?? o.label);

          return (
            <div
              key={q.id}
              className="rounded-lg border border-line bg-surface p-4"
            >
              <div className="mb-3 text-sm font-medium">
                <span className="mr-2 text-content-muted">{idx + 1}.</span>
                {prompt}
              </div>
              <div className="grid gap-2">
                {q.options.map((o, oi) => {
                  const active = answers[q.id] === o.points;
                  return (
                    <button
                      key={o.points}
                      type="button"
                      onClick={() => onChange(q.id, o.points)}
                      className={cn(
                        "rounded-md border px-3 py-2 text-left text-sm transition",
                        active
                          ? "border-accent bg-accent-muted"
                          : "border-line hover:border-accent"
                      )}
                    >
                      {optionLabels[oi] ?? o.label}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
