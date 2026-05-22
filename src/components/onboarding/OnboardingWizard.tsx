import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { useUserStore, useSettingsStore } from "@/store";
import { submitOnboarding, createAccount, createSubscription, fetchMe } from "@/lib/api";
import { useAuthStore } from "@/store";
import { cn } from "@/lib/cn";

import { StepWelcome } from "./StepWelcome";
import { StepGoals, type GoalDraft } from "./StepGoals";
import { StepFinances, type FinancesDraft, type AccountDraft } from "./StepFinances";
import { StepRiskQuiz } from "./StepRiskQuiz";
import { StepPortfolio, type HoldingDraft } from "./StepPortfolio";
import { RISK_QUIZ, scoreToLabel, type AvatarId, type FinancialChallengeId } from "./data";

const STEP_KEYS = ["welcome", "goals", "finances", "risk", "portfolio"] as const;

interface FormState {
  name: string;
  avatar: AvatarId;
  currency: "TRY" | "USD" | "EUR";
  goal: GoalDraft;
  financialChallenges: FinancialChallengeId[];
  finances: FinancesDraft;
  quizAnswers: Record<string, number>;
  holdings: HoldingDraft[];
}

const INITIAL: FormState = {
  name: "",
  avatar: "fox",
  currency: "TRY",
  goal: { type: "home", title: "Buy a home", amount: 0, targetDate: "" },
  financialChallenges: [],
  finances: { monthlyIncome: 0, accounts: [], incomeSources: [] },
  quizAnswers: {},
  holdings: [],
};

export function OnboardingWizard() {
  const { t } = useTranslation("onboarding");
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<FormState>(INITIAL);
  const { setProfile, completeOnboarding } = useUserStore();
  const setDisplayCurrency = useSettingsStore((s) => s.setDisplayCurrency);

  const riskScore = useMemo(
    () => Object.values(form.quizAnswers).reduce((a, b) => a + b, 0),
    [form.quizAnswers]
  );

  const canAdvance = useMemo(() => {
    switch (step) {
      case 0: return form.name.trim().length > 0;
      case 1: return form.goal.amount > 0 && form.goal.targetDate.length > 0;
      case 2: return true;
      case 3: return Object.keys(form.quizAnswers).length === RISK_QUIZ.length;
      case 4: return true;
      default: return false;
    }
  }, [step, form]);

  async function finish() {
    setSubmitting(true);
    try {
      const profile = scoreToLabel(riskScore);
      const incomeCurrency = form.finances.incomeSources[0]?.currency ?? form.currency;

      await submitOnboarding({
        name: form.name.trim(),
        avatar: form.avatar,
        monthly_income: form.finances.monthlyIncome,
        risk_score: riskScore,
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

      if (form.finances.accounts.length > 0) {
        await Promise.allSettled(
          form.finances.accounts.map((acc: AccountDraft) =>
            createAccount({
              name: acc.name,
              kind: acc.kind,
              balance: acc.balance,
              currency: acc.currency,
              institution: acc.institution || null,
            })
          )
        );
      }

      if (form.finances.monthlyIncome > 0) {
        const incomeLabel =
          form.finances.incomeSources[0]?.label ?? `${form.name.trim()}'s income`;
        await createSubscription({
          name: incomeLabel,
          amount: form.finances.monthlyIncome,
          currency: incomeCurrency,
          cycle: "monthly",
          direction: "income",
          category: "income",
        }).catch(() => {});
      }

      // Persist the chosen display currency
      setDisplayCurrency(form.currency);

      setProfile({
        name: form.name.trim(),
        avatar: form.avatar,
        monthlyIncome: form.finances.monthlyIncome,
        riskScore,
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

  const isLast = step === STEP_KEYS.length - 1;

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="w-full max-w-xl">
        {/* Progress stepper */}
        <nav aria-label={t("progressLabel", { defaultValue: "Setup progress" })}>
          <ol role="list" className="mb-8 flex items-center justify-center gap-2">
            {STEP_KEYS.map((key, i) => {
              const stepAriaLabel = i < step
                ? `Step ${i + 1} of ${STEP_KEYS.length}: ${key}, completed`
                : i === step
                  ? `Step ${i + 1} of ${STEP_KEYS.length}: ${key}, current`
                  : `Step ${i + 1} of ${STEP_KEYS.length}: ${key}`;
              return (
                <li key={key} className="flex items-center gap-2">
                  <div
                    aria-current={i === step ? "step" : undefined}
                    aria-label={stepAriaLabel}
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-full border text-xs font-medium transition",
                      i < step && "border-accent bg-accent text-accent-fg",
                      i === step && "border-accent text-accent shadow-glow",
                      i > step && "border-line text-content-muted"
                    )}
                  >
                    {i < step ? <Check aria-hidden="true" className="h-3.5 w-3.5" /> : i + 1}
                  </div>
                  {i < STEP_KEYS.length - 1 && (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "h-px w-6 transition",
                        i < step ? "bg-accent" : "bg-default"
                      )}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Step body */}
        <div className="card min-h-[420px]">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.2 }}
          >
            {step === 0 && (
              <StepWelcome
                name={form.name}
                avatar={form.avatar}
                currency={form.currency}
                onChange={(p) => setForm((s) => ({ ...s, ...p }))}
              />
            )}
            {step === 1 && (
              <StepGoals
                goal={form.goal}
                financialChallenges={form.financialChallenges}
                onChange={(patch) =>
                  setForm((s) => ({
                    ...s,
                    ...(patch.goal && { goal: { ...s.goal, ...patch.goal } }),
                    ...(patch.financialChallenges !== undefined && { financialChallenges: patch.financialChallenges }),
                  }))
                }
              />
            )}
            {step === 2 && (
              <StepFinances
                value={form.finances}
                onChange={(p) => setForm((s) => ({ ...s, finances: { ...s.finances, ...p } }))}
              />
            )}
            {step === 3 && (
              <StepRiskQuiz
                answers={form.quizAnswers}
                onChange={(qid, pts) =>
                  setForm((s) => ({
                    ...s,
                    quizAnswers: { ...s.quizAnswers, [qid]: pts },
                  }))
                }
              />
            )}
            {step === 4 && (
              <StepPortfolio
                holdings={form.holdings}
                onChange={(h) => setForm((s) => ({ ...s, holdings: h }))}
              />
            )}
          </motion.div>
        </div>

        {/* Navigation */}
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-content-muted disabled:opacity-30 hover:text-content"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("back")}
          </button>

          {step === 2 && (
            <span className="text-xs text-content-muted">
              {t("stepOptional")}
            </span>
          )}

          {!isLast ? (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              disabled={!canAdvance}
              className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg shadow-glow disabled:opacity-40"
            >
              {t("next")}
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={finish}
              disabled={submitting}
              className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg shadow-glow disabled:opacity-40"
            >
              <Sparkles className="h-4 w-4" />
              {submitting ? t("settingUp") : t("complete")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
