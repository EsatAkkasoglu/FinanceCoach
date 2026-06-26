import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useSettingsStore, useUserStore, type GeminiModelId } from "@/store";
import { AVATARS } from "@/components/onboarding/data";
import { getProfile, updateProfile, deleteMyAccount, logout, type UserProfile } from "@/lib/api";
import { useAuthStore } from "@/store";
import {
  Cpu, Palette, SlidersHorizontal, UserCircle2, AlertTriangle,
  Moon, Sun, Flame, RotateCcw, Eye, EyeOff, Check, KeyRound,
  Newspaper, Sparkles, Loader2, RefreshCw, Trash2,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { StepRiskQuiz } from "@/components/onboarding/StepRiskQuiz";
import { RISK_QUIZ, scoreToLabel } from "@/components/onboarding/data";
import { CurrencySwitcher } from "@/components/budget/CurrencySwitcher";
import { WatchlistManager } from "@/components/notifications/WatchlistManager";

// ─── UX copy / data ───────────────────────────────────────────────────────────

type CategoryId = "ai" | "appearance" | "behaviour" | "profile" | "danger";

const CATEGORIES: {
  id: CategoryId;
  label: string;
  description: string;
  icon: typeof Cpu;
}[] = [
  { id: "ai",         label: "AI & Keys",   description: "Gemini model, API keys",         icon: Cpu },
  { id: "appearance", label: "Appearance",  description: "Theme",                          icon: Palette },
  { id: "behaviour",  label: "Behaviour",   description: "Demo mode, tone",                icon: SlidersHorizontal },
  { id: "profile",    label: "Profile",     description: "Your info from onboarding",      icon: UserCircle2 },
  { id: "danger",     label: "Danger Zone", description: "Reset & destructive actions",    icon: AlertTriangle },
];

const ACTIVE_MODEL = {
  id: "gemini-3.1-flash-lite-preview" as GeminiModelId,
  name: "Gemini 3.1 Flash-Lite",
  badge: "Active",
  description: "Google's most cost-efficient multimodal model. 2.5× faster than 2.5 Flash, 1M token context window.",
  speed: "Fastest",
  pricing: {
    input: "$0.25 / 1M tokens",
    output: "$1.50 / 1M tokens",
    free: "Free tier available",
  },
};

// ─── Primitives ───────────────────────────────────────────────────────────────

function PanelHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {description && (
        <p className="mt-1 text-sm text-content-muted">{description}</p>
      )}
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-content-muted">{label}</label>
      {children}
      {hint && <p className="text-xs text-content-muted">{hint}</p>}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      {children}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-content">{label}</p>
        {description && (
          <p className="mt-0.5 text-xs text-content-muted">{description}</p>
        )}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200",
          checked ? "bg-accent" : "bg-default"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200",
            checked && "translate-x-4"
          )}
        />
      </button>
    </div>
  );
}

function SecretInput({
  value,
  onChange,
  placeholder,
  icon: Icon,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  icon: typeof KeyRound;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Icon className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-muted" />
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        autoComplete="off"
        className="w-full rounded-lg border border-line bg-surface-raised pl-9 pr-9 py-2 font-mono text-sm text-content placeholder:text-content-muted focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-muted hover:text-content"
        aria-label={visible ? "Hide" : "Reveal"}
      >
        {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

// ─── Panels ───────────────────────────────────────────────────────────────────

function AIPanel() {
  const { t } = useTranslation("settings");
  const {
    geminiApiKey, setGeminiApiKey,
    newsApiKey, setNewsApiKey,
    temperature, setTemperature,
  } = useSettingsStore();

  const [draftGemini, setDraftGemini] = useState(geminiApiKey);
  const [draftNews, setDraftNews] = useState(newsApiKey);
  const [savedGemini, setSavedGemini] = useState(false);
  const [savedNews, setSavedNews] = useState(false);

  const dirtyGemini = draftGemini !== geminiApiKey;
  const dirtyNews = draftNews !== newsApiKey;

  function saveGemini() {
    setGeminiApiKey(draftGemini.trim());
    setSavedGemini(true);
    setTimeout(() => setSavedGemini(false), 1800);
  }
  function saveNews() {
    setNewsApiKey(draftNews.trim());
    setSavedNews(true);
    setTimeout(() => setSavedNews(false), 1800);
  }

  return (
    <>
      <PanelHeader
        title={t("ai.title")}
        description={t("ai.subtitle")}
      />

      <div className="space-y-5">
        {/* Gemini key */}
        <Card>
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-accent" />
            Gemini API Key
          </h3>
          <p className="mb-4 text-xs text-content-muted">
            Required. Get a free key at <span className="font-mono">aistudio.google.com</span>. Stored only on this device.
          </p>

          <Field label="GEMINI_API_KEY">
            <div className="flex gap-2">
              <div className="flex-1">
                <SecretInput
                  value={draftGemini}
                  onChange={(v) => { setDraftGemini(v); setSavedGemini(false); }}
                  placeholder="AIza..."
                  icon={KeyRound}
                />
              </div>
              <button
                onClick={saveGemini}
                disabled={!dirtyGemini || draftGemini.trim() === ""}
                className={cn(
                  "shrink-0 rounded-lg px-3 py-2 text-xs font-medium transition",
                  savedGemini
                    ? "bg-gain/10 text-gain"
                    : dirtyGemini && draftGemini.trim()
                    ? "bg-accent text-white hover:opacity-90"
                    : "bg-surface-raised text-content-muted cursor-not-allowed opacity-50"
                )}
              >
                {savedGemini ? <span className="flex items-center gap-1"><Check className="h-3.5 w-3.5" /> Saved</span> : "Save"}
              </button>
            </div>
          </Field>

          <div className="mt-2 flex items-center gap-2 text-xs">
            {geminiApiKey ? (
              <span className="flex items-center gap-1 text-gain">
                <Check className="h-3 w-3" />
                Active · ends in <span className="font-mono">{geminiApiKey.slice(-4)}</span>
              </span>
            ) : (
              <span className="text-content-muted">No key set — the app will fall back to demo data.</span>
            )}
          </div>
        </Card>

        {/* News key */}
        <Card>
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Newspaper className="h-4 w-4 text-content-muted" />
            News API Key
            <span className="ml-1 rounded bg-surface-raised px-1.5 py-0.5 text-[10px] font-medium text-content-muted">
              Optional
            </span>
          </h3>
          <p className="mb-4 text-xs text-content-muted">
            Powers headlines and sentiment analysis. Without it, the news agent stays idle.
          </p>

          <Field label="NEWS_API_KEY">
            <div className="flex gap-2">
              <div className="flex-1">
                <SecretInput
                  value={draftNews}
                  onChange={(v) => { setDraftNews(v); setSavedNews(false); }}
                  placeholder="Your NewsAPI key"
                  icon={KeyRound}
                />
              </div>
              <button
                onClick={saveNews}
                disabled={!dirtyNews}
                className={cn(
                  "shrink-0 rounded-lg px-3 py-2 text-xs font-medium transition",
                  savedNews
                    ? "bg-gain/10 text-gain"
                    : dirtyNews
                    ? "bg-accent text-white hover:opacity-90"
                    : "bg-surface-raised text-content-muted cursor-not-allowed opacity-50"
                )}
              >
                {savedNews ? <span className="flex items-center gap-1"><Check className="h-3.5 w-3.5" /> Saved</span> : "Save"}
              </button>
            </div>
          </Field>
        </Card>

        {/* Model — fixed, no picker */}
        <Card>
          <h3 className="mb-1 text-sm font-semibold">Model</h3>
          <p className="mb-4 text-xs text-content-muted">
            FinCoach uses a single optimised model for all requests.
          </p>

          <div className="rounded-lg border border-accent bg-accent-muted p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-accent">{ACTIVE_MODEL.name}</span>
                  <span className="rounded-full bg-accent/20 px-2 py-0.5 text-[10px] font-bold text-accent">
                    {ACTIVE_MODEL.badge}
                  </span>
                </div>
                <p className="mt-1 text-xs text-content-muted">{ACTIVE_MODEL.description}</p>
                <p className="mt-1.5 font-mono text-[10px] text-content-muted">{ACTIVE_MODEL.id}</p>
              </div>
              <span className="shrink-0 rounded-md bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
                {ACTIVE_MODEL.speed}
              </span>
            </div>

            {/* Pricing */}
            <div className="mt-3 flex flex-wrap gap-3 border-t border-accent/20 pt-3">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-content-muted">Input</span>
                <span className="font-mono text-[11px] font-semibold text-content">
                  {ACTIVE_MODEL.pricing.input}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-content-muted">Output</span>
                <span className="font-mono text-[11px] font-semibold text-content">
                  {ACTIVE_MODEL.pricing.output}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-medium text-green-400">
                  {ACTIVE_MODEL.pricing.free}
                </span>
              </div>
            </div>
          </div>
        </Card>

        {/* Temperature */}
        <Card>
          <h3 className="mb-1 text-sm font-semibold">Creativity (temperature)</h3>
          <p className="mb-4 text-xs text-content-muted">
            Lower values stay factual. Higher values explore more.
          </p>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="flex-1 accent-accent"
            />
            <span className="w-10 text-right font-mono text-sm tabular-nums">{temperature.toFixed(1)}</span>
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-content-muted">
            <span>Precise</span>
            <span>Balanced</span>
            <span>Creative</span>
          </div>
        </Card>
      </div>
    </>
  );
}

function AppearancePanel() {
  const { t } = useTranslation("settings");
  const { theme, toggleTheme } = useSettingsStore();
  return (
    <>
      <PanelHeader title={t("appearance.title")} description={t("appearance.subtitle")} />
      <Card>
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {theme === "dark"
              ? <Moon className="h-4 w-4 text-content-muted" />
              : <Sun className="h-4 w-4 text-content-muted" />
            }
            <div>
              <p className="text-sm font-medium">{theme === "dark" ? t("appearance.dark") : t("appearance.light")}</p>
              <p className="mt-0.5 text-xs text-content-muted">
                {theme === "dark" ? "Easier on the eyes at night." : "Bright and high-contrast."}
              </p>
            </div>
          </div>
          <button
            role="switch"
            aria-checked={theme === "dark"}
            onClick={toggleTheme}
            className={cn(
              "relative h-5 w-9 rounded-full transition-colors duration-200",
              theme === "dark" ? "bg-accent" : "bg-default"
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200",
                theme === "dark" && "translate-x-4"
              )}
            />
          </button>
        </div>
      </Card>

      <Card>
        <LanguageSwitcher />
      </Card>

      <Card>
        <CurrencyPreference />
      </Card>
    </>
  );
}

function CurrencyPreference() {
  const { t } = useTranslation("settings");
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium">{t("currency.title")}</p>
        <p className="mt-0.5 text-xs text-content-muted">{t("currency.subtitle")}</p>
      </div>
      <CurrencySwitcher />
    </div>
  );
}

function LanguageSwitcher() {
  const { t, i18n } = useTranslation("settings");
  const { t: tCommon } = useTranslation("common");
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium">{t("language.title")}</p>
        <p className="mt-0.5 text-xs text-content-muted">{t("language.subtitle")}</p>
      </div>
      <div className="flex gap-2">
        {(["en", "tr"] as const).map((lang) => (
          <button
            key={lang}
            onClick={() => i18n.changeLanguage(lang)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-medium transition",
              i18n.language === lang
                ? "border-accent bg-accent-muted text-accent"
                : "border-line text-content-muted hover:text-content"
            )}
          >
            {tCommon(lang === "en" ? "languageEn" : "languageTr")}
          </button>
        ))}
      </div>
    </div>
  );
}

function BehaviourPanel() {
  const { t } = useTranslation("settings");
  const { demoMode, setDemoMode, roastMode, setRoastMode } = useSettingsStore();
  return (
    <>
      <PanelHeader title={t("behaviour.title")} description={t("behaviour.subtitle")} />
      <div className="space-y-5">
        <Card>
          <Toggle
            checked={demoMode}
            onChange={setDemoMode}
            label={t("behaviour.demoMode")}
            description={t("behaviour.demoModeDesc")}
          />
        </Card>
        <Card>
          <div className="flex items-start gap-3">
            <Flame className={cn("mt-0.5 h-4 w-4 shrink-0", roastMode ? "text-orange-400" : "text-content-muted")} />
            <div className="flex-1">
              <Toggle
                checked={roastMode}
                onChange={setRoastMode}
                label={t("behaviour.roastMode")}
                description={t("behaviour.roastModeDesc")}
              />
            </div>
          </div>
        </Card>
        <Card>
          <WatchlistManager />
        </Card>
      </div>
    </>
  );
}

const RISK_PROFILES: { id: UserProfile["risk_profile"]; label: string; description: string }[] = [
  { id: "conservative", label: "Conservative", description: "Steady, low-volatility holdings." },
  { id: "balanced",     label: "Balanced",     description: "Mix of growth and stability." },
  { id: "aggressive",   label: "Aggressive",   description: "Higher risk for higher upside." },
];

function ProfilePanel() {
  const { t } = useTranslation("settings");
  const { t: tCommon } = useTranslation("common");
  const setUserProfile = useUserStore((s) => s.setProfile);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [draft, setDraft] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quizOpen, setQuizOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setDraft(p);
        // Keep the persisted Zustand store in sync.
        setUserProfile({
          name: p.name,
          avatar: p.avatar,
          monthlyIncome: p.monthly_income,
          riskScore: p.risk_score,
          riskProfile: p.risk_profile,
        });
      })
      .catch((err) => !cancelled && setError((err as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [setUserProfile]);

  if (loading || !draft || !profile) {
    return (
      <>
        <PanelHeader title={t("profile.title")} />
        <div className="card flex h-32 items-center justify-center">
          {error
            ? <p className="text-sm text-loss">{error}</p>
            : <Loader2 className="h-5 w-5 animate-spin text-content-muted" />}
        </div>
      </>
    );
  }

  const dirty =
    draft.name !== profile.name
    || draft.avatar !== profile.avatar
    || draft.risk_profile !== profile.risk_profile;

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const updated = await updateProfile({
        name: draft.name,
        avatar: draft.avatar,
        risk_profile: draft.risk_profile,
      });
      setProfile(updated);
      setDraft(updated);
      setUserProfile({
        name: updated.name,
        avatar: updated.avatar,
        monthlyIncome: updated.monthly_income,
        riskProfile: updated.risk_profile,
      });
      toast.success("Profile saved");
    } catch (err) {
      toast.error((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    setDraft(profile);
  }

  return (
    <>
      <PanelHeader
        title={t("profile.title")}
        description={t("profile.subtitle")}
      />

      <div className="space-y-5">
        {/* Avatar */}
        <Card>
          <h3 className="mb-3 text-sm font-semibold">{t("profile.spiritAnimal")}</h3>
          <div className="flex flex-wrap gap-2">
            {AVATARS.map((a) => {
              const active = draft.avatar === a.id;
              return (
                <button
                  key={a.id}
                  onClick={() => setDraft({ ...draft, avatar: a.id })}
                  className={cn(
                    "flex h-12 w-12 items-center justify-center rounded-xl border-2 text-2xl leading-none transition",
                    active
                      ? "border-accent bg-accent-muted"
                      : "border-line hover:border-content-muted",
                  )}
                  title={a.label}
                  aria-label={a.label}
                >
                  {a.emoji}
                </button>
              );
            })}
          </div>
        </Card>

        {/* Basics */}
        <Card>
          <h3 className="mb-3 text-sm font-semibold">Basics</h3>
          <div className="space-y-4">
            <Field label={t("profile.name")}>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="w-full rounded-lg border border-line bg-surface-raised px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
          </div>
        </Card>

        {/* Risk */}
        <Card>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h3 className="mb-1 text-sm font-semibold">{t("profile.riskProfile")}</h3>
              <p className="text-xs text-content-muted">
                {t("profile.riskProfileHint")}
              </p>
            </div>
            <button
              onClick={() => setQuizOpen(true)}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-muted/30 px-2.5 py-1.5 text-xs font-medium text-accent transition hover:bg-accent-muted/60"
            >
              <RefreshCw className="h-3 w-3" /> {t("profile.retakeQuiz")}
            </button>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {RISK_PROFILES.map((r) => {
              const active = draft.risk_profile === r.id;
              return (
                <button
                  key={r.id}
                  onClick={() => setDraft({ ...draft, risk_profile: r.id })}
                  className={cn(
                    "rounded-lg border p-3 text-left transition",
                    active
                      ? "border-accent bg-accent-muted"
                      : "border-line hover:border-content-muted",
                  )}
                >
                  <p className={cn("text-sm font-medium", active && "text-accent")}>{r.label}</p>
                  <p className="mt-0.5 text-[11px] text-content-muted">{r.description}</p>
                </button>
              );
            })}
          </div>
        </Card>

        <RetakeQuizModal
          open={quizOpen}
          onClose={() => setQuizOpen(false)}
          onSaved={(score, profileLabel) => {
            setDraft({ ...draft, risk_profile: profileLabel });
            useUserStore.getState().setProfile({ riskScore: score, riskProfile: profileLabel });
            toast.success(t("profile.riskUpdated", { label: profileLabel }));
            setQuizOpen(false);
          }}
        />

        {/* Sticky save bar */}
        {dirty && (
          <div className="sticky bottom-2 flex items-center justify-between gap-2 rounded-lg border border-accent/40 bg-accent-muted/40 px-4 py-2.5 backdrop-blur-sm">
            <span className="text-xs text-content">{t("profile.unsavedChanges")}</span>
            <div className="flex gap-2">
              <button
                onClick={discard}
                className="rounded-lg px-3 py-1.5 text-xs text-content-muted hover:bg-surface-raised"
              >
                {tCommon("cancel")}
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {saving ? tCommon("saving") : t("profile.saveChanges")}
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function RetakeQuizModal({
  open, onClose, onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (score: number, profile: "conservative" | "balanced" | "aggressive") => void;
}) {
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => { if (open) setAnswers({}); }, [open]);

  const answered = Object.keys(answers).length;
  const complete = answered === RISK_QUIZ.length;
  const score = Object.values(answers).reduce((a, b) => a + b, 0);
  const previewLabel = scoreToLabel(score);

  async function submit() {
    if (!complete) {
      toast.error("Answer every question first.");
      return;
    }
    setSubmitting(true);
    try {
      const updated = await updateProfile({
        risk_score: score,
        risk_profile: previewLabel,
      });
      onSaved(updated.risk_score, updated.risk_profile);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Retake risk quiz"
      description="Answer all 5 questions; we'll update your profile when you save."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">Cancel</Button>
          <Button onClick={submit} loading={submitting} disabled={!complete}>
            {complete ? `Save (${previewLabel})` : `Answer ${RISK_QUIZ.length - answered} more`}
          </Button>
        </>
      }
    >
      <StepRiskQuiz
        answers={answers}
        onChange={(qid, pts) => setAnswers((a) => ({ ...a, [qid]: pts }))}
      />
    </Modal>
  );
}

function DangerPanel() {
  const { t } = useTranslation("settings");
  const { resetOnboarding } = useUserStore();
  const setUser = useAuthStore((s) => s.setUser);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  const confirmWord = t("danger.deleteConfirmWord");
  const canDelete = confirmText.trim().toUpperCase() === confirmWord.toUpperCase();

  async function handleDelete() {
    if (!canDelete) return;
    setDeleting(true);
    try {
      const ok = await deleteMyAccount();
      if (!ok) {
        toast.error(t("danger.deleteError"));
        setDeleting(false);
        return;
      }
      toast.success(t("danger.deleteSuccess"));
      // Drop the session — the bearer token now points at a deleted user.
      await logout().catch(() => undefined);
      setUser(null);
    } catch {
      toast.error(t("danger.deleteError"));
      setDeleting(false);
    }
  }

  return (
    <>
      <PanelHeader title={t("danger.title")} description={t("danger.subtitle")} />
      <div className="space-y-4">
        <div className="rounded-xl border border-loss/40 bg-loss/5 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium">{t("danger.resetOnboarding")}</p>
              <p className="mt-0.5 text-xs text-content-muted">
                {t("danger.resetOnboardingDesc")}
              </p>
            </div>
            <button
              onClick={() => {
                if (window.confirm("This will clear your profile and restart onboarding. Continue?")) {
                  resetOnboarding();
                }
              }}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-loss px-3 py-1.5 text-xs font-medium text-loss transition hover:bg-loss hover:text-white"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-loss/40 bg-loss/5 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium">{t("danger.deleteAccount")}</p>
              <p className="mt-0.5 text-xs text-content-muted">
                {t("danger.deleteAccountDesc")}
              </p>
            </div>
            <button
              onClick={() => { setConfirmText(""); setConfirmOpen(true); }}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-loss px-3 py-1.5 text-xs font-medium text-loss transition hover:bg-loss hover:text-white"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t("danger.deleteAccountButton")}
            </button>
          </div>
        </div>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => !deleting && setConfirmOpen(false)}
        title={t("danger.deleteConfirmTitle")}
        description={t("danger.deleteConfirmBody")}
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} type="button" disabled={deleting}>
              {t("danger.deleteCancel")}
            </Button>
            <Button onClick={handleDelete} loading={deleting} disabled={!canDelete}>
              {t("danger.deleteConfirmCta")}
            </Button>
          </>
        }
      >
        <input
          type="text"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={t("danger.deleteConfirmPlaceholder")}
          autoFocus
          className="w-full rounded-lg border border-loss/50 bg-surface-raised px-3 py-2 text-sm text-content placeholder:text-content-muted focus:outline-none focus:ring-1 focus:ring-loss"
        />
      </Modal>
    </>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function Settings() {
  const { t } = useTranslation("settings");
  const [active, setActive] = useState<CategoryId>("ai");

  const CATEGORY_LABELS: Record<CategoryId, string> = {
    ai: t("categories.ai"),
    appearance: t("categories.appearance"),
    behaviour: t("categories.behaviour"),
    profile: t("categories.profile"),
    danger: t("categories.danger"),
  };

  return (
    <div className="mx-auto flex h-full max-w-5xl gap-6 overflow-hidden">
      {/* Sub-nav */}
      <nav className="w-60 shrink-0 sticky top-0 self-start">
        <h1 className="mb-4 px-2 text-2xl font-bold tracking-tight">{t("title")}</h1>
        <div className="flex flex-col gap-0.5">
          {CATEGORIES.map(({ id, icon: Icon }) => {
            const label = CATEGORY_LABELS[id];
            const description = "";
            const isActive = active === id;
            const isDanger = id === "danger";
            return (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={cn(
                  "group flex items-start gap-3 rounded-lg px-3 py-2.5 text-left transition",
                  isActive
                    ? isDanger
                      ? "bg-loss/10 text-loss"
                      : "bg-accent-muted text-accent"
                    : "text-content-muted hover:bg-surface-raised hover:text-content"
                )}
              >
                <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-tight">{label}</p>
                  <p
                    className={cn(
                      "mt-0.5 truncate text-[11px]",
                      isActive ? "opacity-80" : "text-content-muted"
                    )}
                  >
                    {description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </nav>

      {/* Content */}
      <section className="min-w-0 flex-1 pb-12">
        {active === "ai"         && <AIPanel />}
        {active === "appearance" && <AppearancePanel />}
        {active === "behaviour"  && <BehaviourPanel />}
        {active === "profile"    && <ProfilePanel />}
        {active === "danger"     && <DangerPanel />}
        <Disclaimer className="mt-8" />
      </section>
    </div>
  );
}
