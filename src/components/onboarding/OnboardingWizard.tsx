import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { useUserStore } from "@/store";
import { submitOnboarding, createAccount, createSubscription } from "@/lib/api";
import { cn } from "@/lib/cn";

import { StepWelcome } from "./StepWelcome";
import { StepGoals, type GoalDraft } from "./StepGoals";
import { StepFinances, type FinancesDraft, type AccountDraft } from "./StepFinances";
import { StepRiskQuiz } from "./StepRiskQuiz";
import { StepPortfolio, type HoldingDraft } from "./StepPortfolio";
import { RISK_QUIZ, scoreToLabel, type AvatarId } from "./data";

const STEPS = ["Welcome", "Goals", "Finances", "Risk", "Portfolio"] as const;

interface FormState {
  name: string;
  avatar: AvatarId;
  goal: GoalDraft;
  finances: FinancesDraft;
  quizAnswers: Record<string, number>;
  holdings: HoldingDraft[];
}

const INITIAL: FormState = {
  name: "",
  avatar: "fox",
  goal: { type: "home", title: "Buy a home", amount: 0, targetDate: "" },
  finances: { monthlyIncome: 0, accounts: [], incomeSources: [] },
  quizAnswers: {},
  holdings: [],
};

export function OnboardingWizard() {
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<FormState>(INITIAL);
  const { setProfile, completeOnboarding } = useUserStore();

  const riskScore = useMemo(
    () => Object.values(form.quizAnswers).reduce((a, b) => a + b, 0),
    [form.quizAnswers]
  );

  const canAdvance = useMemo(() => {
    switch (step) {
      case 0: return form.name.trim().length > 0;
      case 1: return form.goal.amount > 0 && form.goal.targetDate.length > 0;
      case 2: return form.finances.monthlyIncome > 0;
      case 3: return Object.keys(form.quizAnswers).length === RISK_QUIZ.length;
      case 4: return true;
      default: return false;
    }
  }, [step, form]);

  async function finish() {
    setSubmitting(true);
    try {
      const profile = scoreToLabel(riskScore);
      const incomeCurrency = form.finances.incomeSources[0]?.currency ?? "TRY";

      // 1. Core onboarding
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

      // 2. Create accounts in parallel (best-effort — don't block onboarding)
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

      // 3. Create income subscription if monthly income provided
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
        }).catch(() => {}); // best-effort
      }

      setProfile({
        name: form.name.trim(),
        avatar: form.avatar,
        monthlyIncome: form.finances.monthlyIncome,
        riskScore,
        riskProfile: profile,
      });
      completeOnboarding();
      toast.success(`Welcome aboard, ${form.name.trim()} — you're all set! 🎉`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      toast.error(`Could not save profile: ${msg}`);
      setSubmitting(false);
    }
  }

  const isLast = step === STEPS.length - 1;

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--bg))] p-6">
      <div className="w-full max-w-xl">
        {/* Progress dots */}
        <div className="mb-8 flex items-center justify-center gap-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <div
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full border text-xs font-medium transition",
                  i < step && "border-accent bg-accent text-accent-fg",
                  i === step && "border-accent text-accent shadow-glow",
                  i > step && "border-[hsl(var(--border))] text-[hsl(var(--text-muted))]"
                )}
              >
                {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={cn(
                    "h-px w-6 transition",
                    i < step ? "bg-accent" : "bg-[hsl(var(--border))]"
                  )}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step body */}
        <div className="card min-h-[420px]">
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              {step === 0 && (
                <StepWelcome
                  name={form.name}
                  avatar={form.avatar}
                  onChange={(p) => setForm((s) => ({ ...s, ...p }))}
                />
              )}
              {step === 1 && (
                <StepGoals
                  goal={form.goal}
                  onChange={(p) => setForm((s) => ({ ...s, goal: { ...s.goal, ...p } }))}
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
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-[hsl(var(--text-muted))] disabled:opacity-30 hover:text-[hsl(var(--text))]"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>

          {/* Step hint for finances */}
          {step === 2 && !canAdvance && (
            <span className="text-xs text-[hsl(var(--text-muted))]">
              Enter at least a monthly income to continue
            </span>
          )}

          {!isLast ? (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              disabled={!canAdvance}
              className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg shadow-glow disabled:opacity-40"
            >
              Next
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
              {submitting ? "Setting up…" : "Complete"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
