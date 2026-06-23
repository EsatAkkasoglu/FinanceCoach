/**
 * Static data for the onboarding wizard:
 * - Avatar list (built-in SVG identifiers; rendered by AvatarPicker)
 * - Goal type presets (icon + default label)
 * - Risk quiz questions and per-answer points
 *
 * Total possible quiz score: 125 → mapping (matches backend risk_profiler):
 *   0-50    conservative
 *   51-90   balanced
 *   91-125  aggressive
 */

export const AVATARS = [
  { id: "fox", label: "Fox", emoji: "🦊" },
  { id: "owl", label: "Owl", emoji: "🦉" },
  { id: "bear", label: "Bear", emoji: "🐻" },
  { id: "wolf", label: "Wolf", emoji: "🐺" },
  { id: "tiger", label: "Tiger", emoji: "🐯" },
  { id: "panda", label: "Panda", emoji: "🐼" },
  { id: "lion", label: "Lion", emoji: "🦁" },
  { id: "robot", label: "Robot", emoji: "🤖" },
] as const;

export type AvatarId = (typeof AVATARS)[number]["id"];

export const GOAL_TYPES = [
  { id: "home", label: "Buy a home", emoji: "🏠" },
  { id: "retirement", label: "Retire early", emoji: "🌴" },
  { id: "travel", label: "Travel fund", emoji: "✈️" },
  { id: "freedom", label: "Financial freedom", emoji: "🦅" },
  { id: "education", label: "Education", emoji: "🎓" },
  { id: "emergency", label: "Emergency fund", emoji: "🛟" },
] as const;

export type GoalTypeId = (typeof GOAL_TYPES)[number]["id"];

export const FINANCIAL_CHALLENGES = [
  { id: "too_much_debt",         label: "Too much debt",              emoji: "💳" },
  { id: "inconsistent_income",   label: "Inconsistent income",        emoji: "〰️" },
  { id: "dont_know_where_start", label: "Don't know where to start",  emoji: "🧭" },
  { id: "overspending",          label: "Overspending",               emoji: "🛍️" },
  { id: "want_to_invest",        label: "Want to invest, unsure how", emoji: "📊" },
  { id: "no_emergency_fund",     label: "No emergency fund",          emoji: "🛟" },
] as const;

export type FinancialChallengeId = (typeof FINANCIAL_CHALLENGES)[number]["id"];

export interface QuizOption {
  label: string;
  points: number;
}

export interface QuizQuestion {
  id: string;
  prompt: string;
  options: QuizOption[];
}

export const RISK_QUIZ: QuizQuestion[] = [
  {
    id: "drawdown",
    prompt: "Your $10,000 investment drops to $7,000 in a week. What do you do?",
    options: [
      { label: "Sell everything to stop the bleeding", points: 0 },
      { label: "Sell some, keep the rest", points: 8 },
      { label: "Hold and wait it out", points: 16 },
      { label: "Buy more at the discount", points: 25 },
    ],
  },
  {
    id: "horizon",
    prompt: "When do you need this money?",
    options: [
      { label: "Within 1 year", points: 0 },
      { label: "1-3 years", points: 10 },
      { label: "3-7 years", points: 18 },
      { label: "7+ years", points: 25 },
    ],
  },
  {
    id: "allocation",
    prompt: "Pick the portfolio you'd be most comfortable with.",
    options: [
      { label: "100% bonds, all stability", points: 0 },
      { label: "60/40 stocks/bonds, classic", points: 10 },
      { label: "70/30 stocks/bonds, growth-leaning", points: 20 },
      { label: "100% stocks, all upside", points: 25 },
    ],
  },
  {
    id: "hot_tip",
    prompt: "A friend mentions a hot crypto. You...",
    options: [
      { label: "Ignore it — speculation isn't your thing", points: 5 },
      { label: "Research it for a few days first", points: 15 },
      { label: "Buy a small experimental position", points: 20 },
      { label: "Go all in — gotta seize the moment", points: 10 },
    ],
  },
  {
    id: "long_drawdown",
    prompt: "A bear market drops your portfolio 30%. After a year it's still down. You...",
    options: [
      { label: "Pull everything out", points: 0 },
      { label: "Pause new contributions", points: 10 },
      { label: "Keep dollar-cost averaging", points: 25 },
    ],
  },
];

export function scoreToLabel(score: number): "conservative" | "balanced" | "aggressive" {
  if (score <= 50) return "conservative";
  if (score <= 90) return "balanced";
  return "aggressive";
}

/** Canonical 0-125 risk scale used by scoreToLabel + the backend risk_profiler. */
export const RISK_SCALE_MAX = 125;

/**
 * Short quiz for the one-screen onboarding (URUN_ODAK "hızlı 3 soru"). The full
 * RISK_QUIZ stays available for a later deep re-assessment.
 */
export const RISK_QUIZ_SHORT: QuizQuestion[] = RISK_QUIZ.slice(0, 3);

/** Max achievable raw score for a question set (sum of each question's best option). */
export function maxQuizScore(questions: QuizQuestion[]): number {
  return questions.reduce((sum, q) => sum + Math.max(...q.options.map((o) => o.points)), 0);
}

/**
 * Re-normalize a raw quiz score onto the canonical 0-125 scale so the
 * conservative/balanced/aggressive bands map regardless of how many questions
 * were asked (the 3-question short quiz tops out well below 125 otherwise).
 */
export function normalizeRiskScore(raw: number, questions: QuizQuestion[]): number {
  const max = maxQuizScore(questions);
  if (max <= 0) return 0;
  return Math.round((raw / max) * RISK_SCALE_MAX);
}
