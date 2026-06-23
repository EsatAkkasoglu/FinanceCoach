import { useMemo, useState } from "react";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { useAuthStore, useSettingsStore, useUserStore } from "@/store";
import { fetchMe, submitOnboarding } from "@/lib/api";

import { StepGoals, type GoalDraft } from "./StepGoals";
import { StepRiskQuiz } from "./StepRiskQuiz";
import { StepPortfolio, type HoldingDraft } from "./StepPortfolio";
import { RISK_QUIZ_SHORT, normalizeRiskScore, scoreToLabel } from "./data";

/**
 * One-screen onboarding (docs/URUN_ODAK.md): name + one goal + a 3-question risk
 * quiz + 1-2 holdings, then straight into the app. Deferred details (avatar,
 * display currency, income/accounts, financial challenges) are dropped from v1
 * and collected later, after the user has seen first value. Currency defaults to
 * TRY and avatar to "fox".
 */

interface FormState {
  name: string;
  goal: GoalDraft;
  quizAnswers: Record<string, number>;
  holdings: HoldingDraft[];
}

const INITIAL: FormState = {
  name: "",
  goal: { type: "home", title: "Buy a home", amount: 0, targetDate: "" },
  quizAnswers: {},
  holdings: [],
};

export function OnboardingWizard() {
  const { t } = useTranslation("onboarding");
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<FormState>(INITIAL);
  const { setProfile, completeOnboarding } = useUserStore();
  const setDisplayCurrency = useSettingsStore((s) => s.setDisplayCurrency);

  const rawRisk = useMemo(
    () => Object.values(form.quizAnswers).reduce((a, b) => a + b, 0),
    [form.quizAnswers],
  );
  const riskAnswered = Object.keys(form.quizAnswers).length === RISK_QUIZ_SHORT.length;
  const canComplete =
    form.name.trim().length > 0 && form.goal.amount > 0 && form.goal.targetDate.length > 0;

  async function finish() {
    setSubmitting(true);
    try {
      // Re-normalize the 3-question raw score onto the canonical 0-125 scale so the
      // conservative/balanced/aggressive bands still map. Skipped quiz → balanced 70.
      const effectiveScore = riskAnswered ? normalizeRiskScore(rawRisk, RISK_QUIZ_SHORT) : 70;
      const profile = scoreToLabel(effectiveScore);

      await submitOnboarding({
        name: form.name.trim(),
        avatar: "fox",
        monthly_income: 0,
        risk_score: effectiveScore,
        risk_profile: profile,
        spending_pace: 3,
        goal: {
          title: form.goal.title,
          target_amount: form.goal.amount,
          target_date: form.goal.targetDate,
          icon: form.goal.type,
        },
        holdings: form.holdings
          .filter((h) => h.ticker && h.quantity > 0)
          .map((h) => ({
            ticker: h.ticker,
            quantity: h.quantity,
            cost_basis: h.costBasis,
            asset_class: h.assetClass,
          })),
      });

      setDisplayCurrency("TRY");
      setProfile({
        name: form.name.trim(),
        avatar: "fox",
        monthlyIncome: 0,
        riskScore: effectiveScore,
        riskProfile: profile,
      });
      completeOnboarding();
      const me = await fetchMe();
      if (me) useAuthStore.getState().setUser(me);
      toast.success(t("welcomeBack", { name: form.name.trim() }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      toast.error(`Could not save profile: ${msg}`);
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="w-full max-w-xl space-y-5">
        {/* Name */}
        <div className="card space-y-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("welcome.title")}</h1>
            <p className="mt-1 text-sm text-content-muted">{t("welcome.subtitle")}</p>
          </div>
          <label className="block">
            <span className="text-xs uppercase tracking-wide text-content-muted">
              {t("welcome.whatToCall")}
            </span>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((s) => ({ ...s, name: e.target.value }))}
              placeholder={t("welcome.namePlaceholder")}
              className="mt-2 w-full rounded-lg border border-line bg-surface px-4 py-3 text-base outline-none focus:border-accent"
            />
          </label>
        </div>

        {/* Goal */}
        <div className="card">
          <StepGoals
            goal={form.goal}
            financialChallenges={[]}
            showChallenges={false}
            onChange={(patch) =>
              setForm((s) => ({
                ...s,
                ...(patch.goal && { goal: { ...s.goal, ...patch.goal } }),
              }))
            }
          />
        </div>

        {/* Risk — 3 quick questions */}
        <div className="card">
          <StepRiskQuiz
            questions={RISK_QUIZ_SHORT}
            answers={form.quizAnswers}
            onChange={(qid, pts) =>
              setForm((s) => ({ ...s, quizAnswers: { ...s.quizAnswers, [qid]: pts } }))
            }
          />
        </div>

        {/* Starting portfolio (optional) */}
        <div className="card">
          <StepPortfolio
            holdings={form.holdings}
            onChange={(h) => setForm((s) => ({ ...s, holdings: h }))}
          />
        </div>

        <button
          type="button"
          onClick={finish}
          disabled={submitting || !canComplete}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-3 text-sm font-medium text-accent-fg shadow-glow transition disabled:opacity-40"
        >
          <Sparkles className="h-4 w-4" />
          {submitting ? t("settingUp") : t("complete")}
        </button>
      </div>
    </div>
  );
}
