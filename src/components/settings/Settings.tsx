import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useSettingsStore, useUserStore, type GeminiModelId } from "@/store";
import { AVATARS } from "@/components/onboarding/data";
import { getProfile, updateProfile, type UserProfile } from "@/lib/api";
import {
  Cpu, Palette, SlidersHorizontal, UserCircle2, AlertTriangle,
  Moon, Sun, Flame, RotateCcw, Eye, EyeOff, Check, KeyRound,
  Newspaper, Sparkles, Loader2, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { StepRiskQuiz } from "@/components/onboarding/StepRiskQuiz";
import { RISK_QUIZ, scoreToLabel } from "@/components/onboarding/data";

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

const MODELS: {
  id: GeminiModelId;
  name: string;
  badge?: string;
  description: string;
  speed: string;
}[] = [
  {
    id: "gemini-2.5-pro",
    name: "Gemini 2.5 Pro",
    badge: "Most powerful",
    description: "Best for deep analysis and complex multi-step reasoning.",
    speed: "Slower",
  },
  {
    id: "gemini-2.5-flash",
    name: "Gemini 2.5 Flash",
    badge: "Recommended",
    description: "Strong balance of quality and speed for everyday use.",
    speed: "Fast",
  },
  {
    id: "gemini-2.5-flash-lite",
    name: "Gemini 2.5 Flash-Lite",
    description: "Lightweight 2.5 — quick replies for simple questions.",
    speed: "Faster",
  },
  {
    id: "gemini-2.0-flash",
    name: "Gemini 2.0 Flash",
    description: "Stable default. Good general-purpose performance.",
    speed: "Fast",
  },
  {
    id: "gemini-2.0-flash-lite",
    name: "Gemini 2.0 Flash-Lite",
    description: "Cheapest, fastest. Best for high-volume light tasks.",
    speed: "Fastest",
  },
];

// ─── Primitives ───────────────────────────────────────────────────────────────

function PanelHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {description && (
        <p className="mt-1 text-sm text-[hsl(var(--text-muted))]">{description}</p>
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
      <label className="block text-xs font-medium text-[hsl(var(--text-muted))]">{label}</label>
      {children}
      {hint && <p className="text-xs text-[hsl(var(--text-muted))]">{hint}</p>}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-5">
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
        <p className="text-sm font-medium text-[hsl(var(--text))]">{label}</p>
        {description && (
          <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">{description}</p>
        )}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200",
          checked ? "bg-accent" : "bg-[hsl(var(--border))]"
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
      <Icon className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--text-muted))]" />
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        autoComplete="off"
        className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] pl-9 pr-9 py-2 font-mono text-sm text-[hsl(var(--text))] placeholder:text-[hsl(var(--text-muted))] focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
        aria-label={visible ? "Hide" : "Reveal"}
      >
        {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

// ─── Panels ───────────────────────────────────────────────────────────────────

function AIPanel() {
  const {
    geminiApiKey, setGeminiApiKey,
    newsApiKey, setNewsApiKey,
    model, setModel,
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
        title="AI & API Keys"
        description="FinCoach runs on Google Gemini. Add your keys and choose how the model behaves."
      />

      <div className="space-y-5">
        {/* Gemini key */}
        <Card>
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-accent" />
            Gemini API Key
          </h3>
          <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
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
                    : "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))] cursor-not-allowed opacity-50"
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
              <span className="text-[hsl(var(--text-muted))]">No key set — the app will fall back to demo data.</span>
            )}
          </div>
        </Card>

        {/* News key */}
        <Card>
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <Newspaper className="h-4 w-4 text-[hsl(var(--text-muted))]" />
            News API Key
            <span className="ml-1 rounded bg-[hsl(var(--surface-2))] px-1.5 py-0.5 text-[10px] font-medium text-[hsl(var(--text-muted))]">
              Optional
            </span>
          </h3>
          <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
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
                    : "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))] cursor-not-allowed opacity-50"
                )}
              >
                {savedNews ? <span className="flex items-center gap-1"><Check className="h-3.5 w-3.5" /> Saved</span> : "Save"}
              </button>
            </div>
          </Field>
        </Card>

        {/* Model picker */}
        <Card>
          <h3 className="mb-1 text-sm font-semibold">Model</h3>
          <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
            Pick the Gemini variant. Heavier models reason more deeply but cost more latency.
          </p>

          <div className="flex flex-col gap-2">
            {MODELS.map((m) => {
              const active = model === m.id;
              return (
                <button
                  key={m.id}
                  onClick={() => setModel(m.id)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border p-3 text-left transition",
                    active
                      ? "border-accent bg-accent-muted"
                      : "border-[hsl(var(--border))] hover:border-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))]"
                  )}
                >
                  <span
                    className={cn(
                      "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2",
                      active ? "border-accent" : "border-[hsl(var(--border))]"
                    )}
                  >
                    {active && <span className="h-2 w-2 rounded-full bg-accent" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("text-sm font-medium", active ? "text-accent" : "text-[hsl(var(--text))]")}>
                        {m.name}
                      </span>
                      {m.badge && (
                        <span className="rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                          {m.badge}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">{m.description}</p>
                    <p className="mt-1 font-mono text-[10px] text-[hsl(var(--text-muted))]">{m.id}</p>
                  </div>
                  <span className="mt-0.5 shrink-0 text-[10px] font-medium text-[hsl(var(--text-muted))]">
                    {m.speed}
                  </span>
                </button>
              );
            })}
          </div>
        </Card>

        {/* Temperature */}
        <Card>
          <h3 className="mb-1 text-sm font-semibold">Creativity (temperature)</h3>
          <p className="mb-4 text-xs text-[hsl(var(--text-muted))]">
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
          <div className="mt-1 flex justify-between text-[10px] text-[hsl(var(--text-muted))]">
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
  const { theme, toggleTheme } = useSettingsStore();
  return (
    <>
      <PanelHeader title="Appearance" description="How FinCoach looks on your screen." />
      <Card>
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {theme === "dark"
              ? <Moon className="h-4 w-4 text-[hsl(var(--text-muted))]" />
              : <Sun className="h-4 w-4 text-[hsl(var(--text-muted))]" />
            }
            <div>
              <p className="text-sm font-medium">{theme === "dark" ? "Dark mode" : "Light mode"}</p>
              <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">
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
              theme === "dark" ? "bg-accent" : "bg-[hsl(var(--border))]"
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
    </>
  );
}

function BehaviourPanel() {
  const { demoMode, setDemoMode, roastMode, setRoastMode } = useSettingsStore();
  return (
    <>
      <PanelHeader title="Behaviour" description="How the coach responds and where its data comes from." />
      <div className="space-y-5">
        <Card>
          <Toggle
            checked={demoMode}
            onChange={setDemoMode}
            label="Demo mode"
            description="Use cached responses instead of live API calls. No API key needed."
          />
        </Card>
        <Card>
          <div className="flex items-start gap-3">
            <Flame className={cn("mt-0.5 h-4 w-4 shrink-0", roastMode ? "text-orange-400" : "text-[hsl(var(--text-muted))]")} />
            <div className="flex-1">
              <Toggle
                checked={roastMode}
                onChange={setRoastMode}
                label="Roast mode"
                description="The coach skips the sugarcoating and tells it like it is."
              />
            </div>
          </div>
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
        <PanelHeader title="Your Profile" />
        <div className="card flex h-32 items-center justify-center">
          {error
            ? <p className="text-sm text-loss">{error}</p>
            : <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />}
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
        title="Your Profile"
        description="The coach uses these to tailor advice. Update any time."
      />

      <div className="space-y-5">
        {/* Avatar */}
        <Card>
          <h3 className="mb-3 text-sm font-semibold">Spirit animal</h3>
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
                      : "border-[hsl(var(--border))] hover:border-[hsl(var(--text-muted))]",
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
            <Field label="Name">
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </Field>
          </div>
        </Card>

        {/* Risk */}
        <Card>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h3 className="mb-1 text-sm font-semibold">Risk profile</h3>
              <p className="text-xs text-[hsl(var(--text-muted))]">
                How aggressive should the coach be when suggesting positions?
              </p>
            </div>
            <button
              onClick={() => setQuizOpen(true)}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-accent/40 bg-accent-muted/30 px-2.5 py-1.5 text-xs font-medium text-accent transition hover:bg-accent-muted/60"
              title="Score your risk profile again with the 5-question quiz"
            >
              <RefreshCw className="h-3 w-3" /> Retake quiz
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
                      : "border-[hsl(var(--border))] hover:border-[hsl(var(--text-muted))]",
                  )}
                >
                  <p className={cn("text-sm font-medium", active && "text-accent")}>{r.label}</p>
                  <p className="mt-0.5 text-[11px] text-[hsl(var(--text-muted))]">{r.description}</p>
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
            toast.success(`Risk profile updated to ${profileLabel}`);
            setQuizOpen(false);
          }}
        />

        {/* Sticky save bar */}
        {dirty && (
          <div className="sticky bottom-2 flex items-center justify-between gap-2 rounded-lg border border-accent/40 bg-accent-muted/40 px-4 py-2.5 backdrop-blur-sm">
            <span className="text-xs text-[hsl(var(--text))]">You have unsaved changes.</span>
            <div className="flex gap-2">
              <button
                onClick={discard}
                className="rounded-lg px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))]"
              >
                Discard
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save changes"}
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
  const { resetOnboarding } = useUserStore();
  return (
    <>
      <PanelHeader title="Danger Zone" description="These actions can't be undone." />
      <div className="rounded-xl border border-loss/40 bg-loss/5 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Reset onboarding</p>
            <p className="mt-0.5 text-xs text-[hsl(var(--text-muted))]">
              Clears your name, income, and risk profile, then restarts the setup wizard.
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
    </>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function Settings() {
  const [active, setActive] = useState<CategoryId>("ai");

  return (
    <div className="mx-auto flex h-full max-w-5xl gap-6 overflow-hidden">
      {/* Sub-nav */}
      <nav className="w-60 shrink-0 sticky top-0 self-start">
        <h1 className="mb-4 px-2 text-2xl font-bold tracking-tight">Settings</h1>
        <div className="flex flex-col gap-0.5">
          {CATEGORIES.map(({ id, label, description, icon: Icon }) => {
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
                    : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))]"
                )}
              >
                <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-tight">{label}</p>
                  <p
                    className={cn(
                      "mt-0.5 truncate text-[11px]",
                      isActive ? "opacity-80" : "text-[hsl(var(--text-muted))]"
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
