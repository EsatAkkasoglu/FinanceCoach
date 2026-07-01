/**
 * HeroVisual — the landing page's 3D centerpiece.
 *
 * A layered composition of glassy product cards positioned at different
 * translateZ depths inside a single `perspective` + `preserve-3d` stage.
 * The whole stage tilts toward the pointer (spring-smoothed), so the depth
 * reads as real parallax rather than a flat mock-up. Pure CSS 3D + transforms
 * — no WebGL — to keep the first paint fast.
 *
 * Motion is gated on `prefers-reduced-motion`: the resting pose still has a
 * gentle 3D tilt, but pointer tracking and the floating bob are disabled.
 */
import { lazy, Suspense, useRef } from "react";
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
  useReducedMotion,
} from "framer-motion";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, ShieldCheck, Sparkles } from "lucide-react";

// WebGL orb is code-split — the CSS card stack paints instantly without it.
const HeroOrb3D = lazy(() => import("@/components/three/HeroOrb3D"));

function BrandMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <g stroke="#FFFFFF" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 50 L20 16 L42 16 L52 6" />
        <path d="M46 6 L52 6 L52 12" />
        <path d="M20 32 L36 32" />
      </g>
    </svg>
  );
}

/** Smooth upward area chart used inside the net-worth panel. */
function AreaChart() {
  return (
    <svg viewBox="0 0 320 120" className="h-full w-full" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="hv-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1FB57A" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#1FB57A" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M0,96 C40,90 60,70 96,72 C132,74 150,40 192,46 C228,51 250,22 288,18 L320,12 L320,120 L0,120 Z"
        fill="url(#hv-fill)"
      />
      <path
        d="M0,96 C40,90 60,70 96,72 C132,74 150,40 192,46 C228,51 250,22 288,18 L320,12"
        fill="none"
        stroke="#1FB57A"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="320" cy="12" r="4" fill="#1FB57A" />
      <circle cx="320" cy="12" r="7" fill="#1FB57A" opacity="0.25" />
    </svg>
  );
}

/** Tiny rising sparkline for the delta pill. */
function Sparkline() {
  return (
    <svg viewBox="0 0 48 18" className="h-4 w-12" aria-hidden="true">
      <path
        d="M1,15 L9,11 L17,13 L25,7 L33,9 L41,3 L47,2"
        fill="none"
        stroke="#22C55E"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Circular progress ring for the goal card. */
function ProgressRing({ value = 62 }: { value?: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const offset = c - (value / 100) * c;
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16" aria-hidden="true">
      <circle cx="32" cy="32" r={r} fill="none" stroke="hsl(var(--border))" strokeWidth="6" />
      <circle
        cx="32"
        cy="32"
        r={r}
        fill="none"
        stroke="#1FB57A"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 32 32)"
      />
      <text x="32" y="37" textAnchor="middle" className="fill-content text-[15px] font-bold font-mono">
        {value}%
      </text>
    </svg>
  );
}

/** A positioned layer at a fixed depth, optionally bobbing. */
function Layer({
  z,
  className,
  delay = 0,
  float = true,
  children,
}: {
  z: number;
  className?: string;
  delay?: number;
  float?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`absolute ${className ?? ""}`} style={{ transform: `translateZ(${z}px)` }}>
      <div className={float ? "animate-float" : ""} style={{ animationDelay: `${delay}s` }}>
        {children}
      </div>
    </div>
  );
}

export function HeroVisual() {
  const { t } = useTranslation("landing");
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);

  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const cfg = { stiffness: 140, damping: 18, mass: 0.4 };
  // Resting pose (pointer at center) sits square; pointer tilts it symmetrically.
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [11, -11]), cfg);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [-9, 9]), cfg);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (reduce) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  }
  function onLeave() {
    px.set(0);
    py.set(0);
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className="relative mx-auto w-full max-w-[34rem] select-none"
      style={{ perspective: "1400px" }}
      aria-hidden="true"
    >
      {/* Holographic WebGL orb behind the card stack — shares the pointer so
          the CSS parallax and the orb tilt read as one composition. */}
      {!reduce && (
        <Suspense fallback={null}>
          <div className="pointer-events-none absolute -inset-16 sm:-inset-20" aria-hidden="true">
            <HeroOrb3D />
          </div>
        </Suspense>
      )}

      <motion.div
        className="relative aspect-[4/5] sm:aspect-[6/5]"
        style={{ transformStyle: "preserve-3d", rotateX, rotateY }}
      >
        {/* ── Base panel: net worth + portfolio chart ── */}
        <Layer z={0} className="inset-x-2 top-32 sm:inset-x-6 sm:top-24" float={!reduce} delay={0}>
          <div className="rounded-2xl border border-line bg-surface/70 p-5 shadow-2xl backdrop-blur-xl">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-overline uppercase text-content-muted">
                  {t("hero.card.balanceLabel")}
                </p>
                <p className="mt-1 font-mono text-2xl font-bold tracking-tight text-content">₺248K</p>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-1 text-xs font-semibold text-accent">
                <ArrowUpRight className="h-3 w-3" />
                {t("hero.card.balanceDelta")}
              </span>
            </div>
            <div className="mt-3 h-24 w-full">
              <AreaChart />
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3">
              {["Stocks", "Funds", "Cash"].map((k, i) => (
                <div key={k}>
                  <p className="text-[11px] text-content-muted">{k}</p>
                  <p className="font-mono text-sm font-semibold text-content">
                    {["54%", "31%", "15%"][i]}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </Layer>

        {/* ── Coach chat card (front, top-left) ── */}
        <Layer z={70} className="-left-2 -top-4 w-[60%] sm:left-2 sm:top-0 sm:w-[60%]" float={!reduce} delay={1.1}>
          <div className="rounded-2xl border border-line bg-surface/80 p-3.5 shadow-2xl backdrop-blur-xl">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-accent">
                <BrandMark size={13} />
              </span>
              <span className="text-xs font-semibold text-content">FinCoach</span>
              <span className="ml-auto flex items-center gap-1 text-[10px] text-accent">
                <Sparkles className="h-3 w-3" /> AI
              </span>
            </div>
            <p className="mt-2.5 ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-sm bg-surface-raised px-3 py-1.5 text-[11px] leading-snug text-content">
              {t("hero.card.coachQuestion")}
            </p>
            <p className="mt-2 w-fit max-w-[95%] rounded-2xl rounded-bl-sm bg-accent/12 px-3 py-1.5 text-[11px] leading-snug text-content">
              {t("hero.card.coachAnswer")}
            </p>
            <span className="mt-2 inline-flex items-center gap-1 rounded-full border border-line bg-bg/60 px-2 py-0.5 text-[10px] text-content-muted">
              <ShieldCheck className="h-2.5 w-2.5 text-accent" />
              {t("hero.card.citation")}
            </span>
          </div>
        </Layer>

        {/* ── Delta pill (front, top-right) ── */}
        <Layer z={110} className="right-0 top-10 sm:-right-2 sm:top-6" float={!reduce} delay={0.5}>
          <div className="flex items-center gap-2 rounded-xl border border-line bg-surface/85 px-3 py-2 shadow-xl backdrop-blur-xl">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gain/15 text-gain">
              <ArrowUpRight className="h-4 w-4" />
            </span>
            <div>
              <p className="font-mono text-sm font-bold leading-none text-gain">+12.4%</p>
              <p className="mt-0.5 text-[10px] text-content-muted">this month</p>
            </div>
            <Sparkline />
          </div>
        </Layer>

        {/* ── Goal ring card (front, bottom-left) ── */}
        <Layer z={95} className="bottom-2 left-2 sm:bottom-1 sm:left-0 sm:-left-3" float={!reduce} delay={1.7}>
          <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface/85 p-3 shadow-xl backdrop-blur-xl">
            <ProgressRing value={62} />
            <div className="pr-1">
              <p className="text-[11px] font-medium text-content">{t("hero.card.goalLabel")}</p>
              <p className="mt-0.5 text-[11px] text-content-muted">{t("hero.card.goalProgress")}</p>
            </div>
          </div>
        </Layer>

        {/* ── Decorative floating orbs ── */}
        <Layer z={150} className="right-8 bottom-10" float={!reduce} delay={0.2}>
          <span className="block h-3 w-3 rounded-full bg-accent shadow-glow" />
        </Layer>
        <Layer z={40} className="left-10 top-2" float={!reduce} delay={2.2}>
          <span className="block h-2 w-2 rounded-full bg-warning/80" />
        </Layer>
        <Layer z={130} className="right-16 top-24" float={!reduce} delay={1.4}>
          <span className="block h-1.5 w-1.5 rounded-full bg-content/40" />
        </Layer>
      </motion.div>
    </div>
  );
}
