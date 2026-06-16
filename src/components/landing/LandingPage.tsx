/**
 * LandingPage — full marketing page shown to logged-out visitors.
 *
 * Sections: sticky nav · hero (with 3D HeroVisual) · trust strip · stats ·
 * features · how-it-works · showcase · testimonials · pricing · final CTA ·
 * footer/contact. Scroll-reveal via framer-motion, all gated on
 * prefers-reduced-motion. CTAs route to /login and /register; the "live demo"
 * button signs in with the shared demo account.
 *
 * NOTE: testimonials and Pro/Team pricing are illustrative placeholders —
 * swap in real quotes / plans before any public launch.
 */
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import {
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
  useVelocity,
  type MotionValue,
} from "framer-motion";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Menu,
  X,
  Globe,
  ArrowRight,
  ArrowDownToLine,
  Loader2,
  Sparkles,
  ShieldCheck,
  Check,
  MessageSquare,
  Briefcase,
  Wallet,
  Coins,
  Target,
  FileText,
  TrendingUp,
  Star,
  Mail,
  type LucideIcon,
} from "lucide-react";
import { loginDemo } from "@/lib/api";
import { useAuthStore } from "@/store";
import { buildLocalizedPath, getLanguageFromPath, type SupportedLanguage } from "@/lib/routing";
import { toast } from "sonner";
import { HeroVisual } from "./HeroVisual";
import { TiltCard } from "@/components/ui/TiltCard";

// WebGL constellation is code-split so it never blocks the hero's first paint.
const LandingBackground3D = lazy(() => import("./LandingBackground3D"));

/* ── shared types for i18n returnObjects ── */
type Feature = { icon: string; title: string; desc: string };
type Step = { title: string; desc: string };
type Stat = { value: string; label: string };
type ShowRow = { eyebrow: string; title: string; desc: string; bullets: string[] };
type Testi = { quote: string; name: string; role: string };
type Tier = {
  name: string;
  price: string;
  period: string;
  desc: string;
  features: string[];
  cta: string;
  featured: boolean;
  badge: string;
};

const FEATURE_ICONS: Record<string, LucideIcon> = {
  coach: MessageSquare,
  portfolio: Briefcase,
  budget: Wallet,
  funds: Coins,
  goals: Target,
  documents: FileText,
};

const STEP_ICONS: LucideIcon[] = [ArrowDownToLine, Sparkles, TrendingUp];

function scrollToId(id: string, smooth: boolean) {
  document.getElementById(id)?.scrollIntoView({
    behavior: smooth ? "smooth" : "auto",
    block: "start",
  });
}

function BrandMark({ size = 18 }: { size?: number }) {
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

function Wordmark() {
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent shadow-glow">
        <BrandMark />
      </span>
      <span className="text-base font-bold tracking-tight">FinCoach</span>
    </span>
  );
}

/**
 * Window scroll position as a MotionValue.
 *
 * We drive parallax from this rather than framer-motion's `useScroll()`: the
 * page scrolls on the window (the root uses `overflow-x-clip`, so it is not a
 * scroll container), and useScroll's container auto-detection binds to the
 * wrong element here and freezes the value. A passive window listener is
 * reliable — the same pattern LandingNav uses for its scrolled state.
 */
function useScrollY() {
  const scrollY = useMotionValue(0);
  useEffect(() => {
    const update = () => scrollY.set(window.scrollY);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, [scrollY]);
  return scrollY;
}

/** Whole-page scroll progress 0…1 (same manual pattern as useScrollY). */
function useDocProgress() {
  const progress = useMotionValue(0);
  useEffect(() => {
    const update = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress.set(max > 0 ? Math.min(1, window.scrollY / max) : 0);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [progress]);
  return progress;
}

/**
 * Scrub progress (0…1) of a tall wrapper as it travels through the viewport —
 * drives the pinned showcase. 0 = wrapper top hits viewport top, 1 = wrapper
 * bottom hits viewport bottom.
 */
function useElementProgress(ref: React.RefObject<HTMLElement>) {
  const progress = useMotionValue(0);
  useEffect(() => {
    const update = () => {
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      progress.set(total > 0 ? Math.min(1, Math.max(0, -rect.top / total)) : 0);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [ref, progress]);
  return progress;
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** Thin gradient bar along the top edge tracking page scroll. */
function ScrollProgressBar() {
  const reduce = useReducedMotion();
  const progress = useDocProgress();
  const smoothed = useSpring(progress, { stiffness: 180, damping: 28, mass: 0.3 });
  return (
    <motion.div
      aria-hidden="true"
      style={{ scaleX: reduce ? progress : smoothed }}
      className="fixed inset-x-0 top-0 z-[60] h-0.5 origin-left bg-gradient-to-r from-accent via-emerald-400 to-teal-300"
    />
  );
}

/**
 * Headline that reveals word by word as it scrolls into view — each word
 * rises out of an overflow-hidden slot with a small stagger.
 */
function WordReveal({ text, className }: { text: string; className?: string }) {
  const reduce = useReducedMotion();
  if (reduce) return <h2 className={className}>{text}</h2>;
  const words = text.split(" ");
  return (
    <h2 className={className} aria-label={text}>
      {words.map((word, i) => (
        <span key={i} aria-hidden="true" className="inline-block overflow-hidden align-bottom">
          <motion.span
            className="inline-block"
            initial={{ y: "110%" }}
            whileInView={{ y: 0 }}
            viewport={{ once: true, margin: "-70px" }}
            transition={{ duration: 0.55, delay: i * 0.055, ease: [0.22, 1, 0.36, 1] }}
          >
            {word}
            {i < words.length - 1 ? " " : ""}
          </motion.span>
        </span>
      ))}
    </h2>
  );
}

/* ── scroll-reveal wrapper ── */
function Reveal({
  children,
  delay = 0,
  y = 20,
  className,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.55, delay, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <Reveal>
        <span className="inline-block rounded-full border border-line bg-surface px-3 py-1 text-overline uppercase text-accent">
          {eyebrow}
        </span>
      </Reveal>
      <WordReveal
        text={title}
        className="mt-4 font-display text-h1 font-bold tracking-tight md:text-display"
      />
      {subtitle && (
        <Reveal delay={0.1}>
          <p className="mt-3 text-body text-content-muted">{subtitle}</p>
        </Reveal>
      )}
    </div>
  );
}

/* ─────────────────────────── Nav ─────────────────────────── */
function LandingNav({
  lang,
  onLang,
  onLogin,
  onRegister,
}: {
  lang: SupportedLanguage;
  onLang: (l: SupportedLanguage) => void;
  onLogin: () => void;
  onRegister: () => void;
}) {
  const { t } = useTranslation("landing");
  const reduce = useReducedMotion();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const links: { id: string; label: string }[] = [
    { id: "features", label: t("nav.features") },
    { id: "how", label: t("nav.howItWorks") },
    { id: "pricing", label: t("nav.pricing") },
    { id: "contact", label: t("nav.contact") },
  ];

  function go(id: string) {
    setOpen(false);
    scrollToId(id, !reduce);
  }

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
        scrolled || open
          ? "border-b border-line bg-bg/80 backdrop-blur-xl"
          : "border-b border-transparent"
      }`}
    >
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <button onClick={() => scrollToId("top", !reduce)} className="shrink-0" aria-label="FinCoach">
          <Wordmark />
        </button>

        {/* desktop links */}
        <div className="hidden items-center gap-1 md:flex">
          {links.map((l) => (
            <button
              key={l.id}
              onClick={() => go(l.id)}
              className="rounded-lg px-3 py-2 text-sm font-medium text-content-muted transition hover:bg-surface-raised hover:text-content"
            >
              {l.label}
            </button>
          ))}
        </div>

        {/* desktop actions */}
        <div className="hidden items-center gap-2 md:flex">
          <div className="relative">
            <button
              onClick={() => setLangOpen((v) => !v)}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-content-muted transition hover:bg-surface-raised hover:text-content"
              aria-label={lang === "tr" ? "Dil" : "Language"}
            >
              <Globe className="h-4 w-4" />
            </button>
            {langOpen && (
              <div className="absolute right-0 top-full mt-2 flex flex-col gap-1 rounded-xl border border-line bg-surface p-2 shadow-xl">
                {(["tr", "en"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => {
                      onLang(l);
                      setLangOpen(false);
                    }}
                    className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                      lang === l
                        ? "bg-accent text-white"
                        : "text-content-muted hover:bg-surface-raised hover:text-content"
                    }`}
                  >
                    <span className="flex h-5 w-7 items-center justify-center rounded bg-white/10 font-mono text-[10px] font-semibold uppercase">
                      {l}
                    </span>
                    {l === "tr" ? "Türkçe" : "English"}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            onClick={onLogin}
            className="rounded-lg px-3.5 py-2 text-sm font-medium text-content-muted transition hover:bg-surface-raised hover:text-content"
          >
            {t("nav.signIn")}
          </button>
          <button
            onClick={onRegister}
            className="group inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-glow transition hover:opacity-90"
          >
            {t("nav.getStarted")}
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
        </div>

        {/* mobile toggle */}
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-content md:hidden"
          aria-label="Menu"
          aria-expanded={open}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </nav>

      {/* mobile panel */}
      {open && (
        <div className="border-t border-line bg-bg/95 px-4 py-4 backdrop-blur-xl md:hidden">
          <div className="flex flex-col gap-1">
            {links.map((l) => (
              <button
                key={l.id}
                onClick={() => go(l.id)}
                className="rounded-lg px-3 py-2.5 text-left text-sm font-medium text-content-muted transition hover:bg-surface-raised hover:text-content"
              >
                {l.label}
              </button>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
            <button
              onClick={onLogin}
              className="flex-1 rounded-lg border border-line px-3 py-2.5 text-sm font-medium text-content transition hover:bg-surface-raised"
            >
              {t("nav.signIn")}
            </button>
            <button
              onClick={onRegister}
              className="flex-1 rounded-lg bg-accent px-3 py-2.5 text-sm font-semibold text-white shadow-glow"
            >
              {t("nav.getStarted")}
            </button>
          </div>
          <div className="mt-3 flex justify-center gap-2">
            {(["tr", "en"] as const).map((l) => (
              <button
                key={l}
                onClick={() => onLang(l)}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  lang === l ? "bg-accent text-white" : "text-content-muted hover:bg-surface-raised"
                }`}
              >
                <span className="flex h-5 w-7 items-center justify-center rounded bg-white/10 font-mono text-[10px] font-semibold uppercase">
                  {l}
                </span>
                {l === "tr" ? "Türkçe" : "English"}
              </button>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}

/* ─────────────────────────── Hero ─────────────────────────── */
/**
 * A soft glow blob that drifts opposite the pointer at its own depth rate.
 * `factor` is the parallax strength (0.02 = far/slow, 0.1 = near/fast).
 * Purely decorative — never in the a11y tree, frozen under reduced motion.
 */
function DepthBlob({
  px,
  py,
  factor,
  className,
  reduce,
}: {
  px: MotionValue<number>;
  py: MotionValue<number>;
  factor: number;
  className: string;
  reduce: boolean | null;
}) {
  const range = factor * 900; // 0.02→18px … 0.1→90px of travel
  const cfg = { stiffness: 60, damping: 20, mass: 0.8 };
  const x = useSpring(useTransform(px, [-0.5, 0.5], [-range, range]), cfg);
  const y = useSpring(useTransform(py, [-0.5, 0.5], [-range, range]), cfg);
  return (
    <motion.div
      aria-hidden="true"
      style={reduce ? undefined : { x, y, willChange: "transform" }}
      className={className}
    />
  );
}

function Hero({
  onRegister,
  onDemo,
  demoLoading,
}: {
  onRegister: () => void;
  onDemo: () => void;
  demoLoading: boolean;
}) {
  const { t } = useTranslation("landing");
  const reduce = useReducedMotion();
  const enter = (d: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 22 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.6, delay: d, ease: "easeOut" as const },
        };

  // Scroll-parallax: copy and the 3D visual drift at different rates as the
  // hero scrolls out, for depth. The hero sits at the top of the page, so
  // ~0–560px of window scroll covers leaving it. Disabled under reduced motion.
  const scrollY = useScrollY();
  const copyY = useTransform(scrollY, [0, 560], [0, 36]);
  const copyOpacity = useTransform(scrollY, [0, 620], [1, 0.25]);
  const visualY = useTransform(scrollY, [0, 560], [0, -80]);
  // Exit choreography: the 3D stack shrinks, tips back and dims as it leaves.
  const visualScale = useTransform(scrollY, [0, 640], [1, 0.88]);
  const visualRotate = useTransform(scrollY, [0, 640], [0, -5]);
  const visualOpacity = useTransform(scrollY, [0, 640], [1, 0.3]);

  // Pointer-parallax for the depth layers. Normalized to -0.5…0.5 over the
  // section and written through a single rAF so a burst of mousemove events
  // collapses to one update per frame. Desktop only — touch never fires move.
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const rafRef = useRef<number | null>(null);
  const pending = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  function onPointerMove(e: React.MouseEvent<HTMLElement>) {
    if (reduce) return;
    const r = e.currentTarget.getBoundingClientRect();
    pending.current = {
      x: (e.clientX - r.left) / r.width - 0.5,
      y: (e.clientY - r.top) / r.height - 0.5,
    };
    if (rafRef.current == null) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        if (pending.current) {
          px.set(pending.current.x);
          py.set(pending.current.y);
        }
      });
    }
  }
  function onPointerLeave() {
    px.set(0);
    py.set(0);
  }

  return (
    <section
      id="top"
      onMouseMove={onPointerMove}
      onMouseLeave={onPointerLeave}
      className="relative flex min-h-screen items-center px-4 pt-28 pb-16 sm:px-6 md:pb-24 lg:px-8"
    >
      {/* depth layers — drift with the pointer at three different rates */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
        <DepthBlob
          px={px}
          py={py}
          factor={0.02}
          reduce={reduce}
          className="absolute left-[8%] top-[18%] h-72 w-72 rounded-full bg-accent/10 blur-[120px]"
        />
        <DepthBlob
          px={px}
          py={py}
          factor={0.05}
          reduce={reduce}
          className="absolute right-[12%] top-[12%] h-80 w-80 rounded-full bg-emerald-400/10 blur-[110px]"
        />
        <DepthBlob
          px={px}
          py={py}
          factor={0.1}
          reduce={reduce}
          className="absolute bottom-[10%] left-[40%] h-64 w-64 rounded-full bg-accent/15 blur-[90px]"
        />
      </div>

      <div className="mx-auto grid w-full max-w-7xl items-center gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        {/* copy */}
        <motion.div
          style={reduce ? undefined : { y: copyY, opacity: copyOpacity }}
          className="text-center lg:text-left"
        >
          <motion.span
            {...enter(0)}
            className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-medium text-content-muted"
          >
            <span className="flex h-2 w-2 rounded-full bg-accent">
              <span className="h-2 w-2 animate-ping rounded-full bg-accent" />
            </span>
            {t("hero.badge")}
          </motion.span>

          <motion.h1
            {...enter(0.08)}
            style={{ fontSize: "clamp(2.5rem, 5vw, 4rem)" }}
            className="mt-6 font-display font-bold leading-[1.04] tracking-tight"
          >
            {t("hero.titleLead")}{" "}
            <span className="bg-gradient-to-r from-accent to-emerald-400 bg-clip-text text-transparent">
              {t("hero.titleAccent")}
            </span>
          </motion.h1>

          <motion.p
            {...enter(0.14)}
            className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-content-muted lg:mx-0"
          >
            {t("hero.subtitle")}
          </motion.p>

          <motion.div
            {...enter(0.2)}
            className="mt-8 flex flex-col items-center gap-3 sm:flex-row lg:justify-start"
          >
            <button
              onClick={onRegister}
              className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-7 py-4 text-sm font-semibold text-white shadow-glow transition duration-200 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] hover:scale-[1.03] hover:shadow-[0_12px_40px_-8px_hsl(var(--accent)/0.65)] sm:w-auto"
            >
              {t("hero.ctaPrimary")}
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </button>
            <button
              onClick={onDemo}
              disabled={demoLoading}
              aria-busy={demoLoading}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-surface px-7 py-4 text-sm font-semibold text-content transition hover:border-content-muted hover:bg-surface-raised disabled:opacity-60 sm:w-auto"
            >
              {demoLoading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {demoLoading ? t("hero.ctaDemoLoading") : t("hero.ctaDemo")}
            </button>
          </motion.div>

          <motion.p {...enter(0.26)} className="mt-4 text-caption text-content-muted">
            {t("hero.microcopy")}
          </motion.p>
        </motion.div>

        {/* 3D visual */}
        <motion.div
          {...(reduce
            ? {}
            : {
                initial: { opacity: 0, scale: 0.94 },
                animate: { opacity: 1, scale: 1 },
                transition: { duration: 0.8, delay: 0.2, ease: "easeOut" as const },
              })}
          style={
            reduce
              ? undefined
              : { y: visualY, scale: visualScale, rotate: visualRotate, opacity: visualOpacity }
          }
          className="relative"
        >
          <HeroVisual />
        </motion.div>
      </div>
    </section>
  );
}

/* ─────────────────────── Trust strip ─────────────────────── */
function TrustStrip() {
  const { t } = useTranslation("landing");
  const reduce = useReducedMotion();
  const sources = t("trust.sources", { returnObjects: true }) as unknown as string[];
  const row = [...sources, ...sources];
  // Scroll-velocity skew: fast scrolling leans the marquee like it has inertia.
  const scrollY = useScrollY();
  const velocity = useVelocity(scrollY);
  const skewX = useSpring(useTransform(velocity, [-1500, 1500], [5, -5]), {
    stiffness: 240,
    damping: 32,
  });
  return (
    <section className="border-y border-line bg-surface/40 py-6">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="mb-4 text-center text-overline uppercase text-content-muted">{t("trust.label")}</p>
        <motion.div style={reduce ? undefined : { skewX }} className="marquee-mask overflow-hidden">
          <div className="animate-marquee flex w-max items-center gap-10">
            {row.map((s, i) => (
              <span
                key={`${s}-${i}`}
                className="flex items-center gap-2 whitespace-nowrap text-sm font-semibold text-content-muted"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-accent/70" />
                {s}
              </span>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/* ───────────────────────── Stats ─────────────────────────── */
/** Stat numeral that counts up from zero once it scrolls into view. */
function StatValue({ value }: { value: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLParagraphElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const match = /^(\D*?)(\d+)(.*)$/.exec(value);
  const target = match ? parseInt(match[2], 10) : 0;
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!inView || !match || reduce) return;
    const t0 = performance.now();
    const duration = 1100;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / duration);
      setN(Math.round(target * (1 - (1 - p) ** 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView, reduce, target]);

  const display = match && !reduce ? `${match[1]}${n}${match[3]}` : value;
  return (
    <p ref={ref} className="text-gradient font-mono text-3xl font-bold tracking-tight md:text-4xl">
      {display}
    </p>
  );
}

function StatsBand() {
  const { t } = useTranslation("landing");
  const stats = t("stats.items", { returnObjects: true }) as unknown as Stat[];
  return (
    <section className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-6 lg:grid-cols-4">
        {stats.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.06}>
            <TiltCard maxTilt={5}>
              <div className="glass rounded-2xl p-5 text-center">
                <StatValue value={s.value} />
                <p className="mt-1.5 text-caption text-content-muted">{s.label}</p>
              </div>
            </TiltCard>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* ──────────────────────── Features ───────────────────────── */
function FeaturesSection() {
  const { t } = useTranslation("landing");
  const items = t("features.items", { returnObjects: true }) as unknown as Feature[];
  return (
    <section id="features" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:px-8">
      <SectionHeading
        eyebrow={t("features.eyebrow")}
        title={t("features.title")}
        subtitle={t("features.subtitle")}
      />
      <div className="mx-auto mt-14 grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((f, i) => {
          const Icon = FEATURE_ICONS[f.icon] ?? Sparkles;
          return (
            <Reveal key={f.title} delay={(i % 3) * 0.08} className="h-full">
              <TiltCard maxTilt={6} className="h-full">
                <div className="glass group h-full rounded-2xl p-6 transition duration-300 hover:border-accent/40 hover:shadow-card-hover">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/12 text-accent transition group-hover:bg-accent group-hover:text-white">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="mt-4 text-h4 font-semibold">{f.title}</h3>
                  <p className="mt-2 text-body-sm text-content-muted">{f.desc}</p>
                </div>
              </TiltCard>
            </Reveal>
          );
        })}
      </div>
    </section>
  );
}

/* ──────────────────────── How it works ───────────────────── */
function HowSection() {
  const { t } = useTranslation("landing");
  const steps = t("how.steps", { returnObjects: true }) as unknown as Step[];
  return (
    <section id="how" className="scroll-mt-24 border-y border-line bg-surface/30 px-4 py-20 sm:px-6 lg:px-8">
      <SectionHeading eyebrow={t("how.eyebrow")} title={t("how.title")} subtitle={t("how.subtitle")} />
      <div className="mx-auto mt-14 grid max-w-5xl gap-6 md:grid-cols-3">
        {steps.map((s, i) => {
          const Icon = STEP_ICONS[i] ?? Sparkles;
          return (
            <Reveal key={s.title} delay={i * 0.1}>
              <div className="glass relative h-full rounded-2xl p-6">
                <span className="absolute right-5 top-5 font-mono text-5xl font-bold text-content/5">
                  {i + 1}
                </span>
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/12 text-accent">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="mt-4 text-h4 font-semibold">{s.title}</h3>
                <p className="mt-2 text-body-sm text-content-muted">{s.desc}</p>
              </div>
            </Reveal>
          );
        })}
      </div>
    </section>
  );
}

/* ──────────────────────── Showcase ───────────────────────── */
function ShowcaseMock({ index }: { index: number }) {
  // Two lightweight, on-brand mock visuals.
  if (index === 0) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-5 shadow-2xl">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent">
            <BrandMark size={14} />
          </span>
          <span className="text-sm font-semibold">FinCoach</span>
          <span className="ml-auto flex items-center gap-1 text-xs text-accent">
            <Sparkles className="h-3.5 w-3.5" /> AI
          </span>
        </div>
        <p className="mt-3 ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-surface-raised px-3.5 py-2 text-sm">
          Is now a good time to add to my tech holdings?
        </p>
        <p className="mt-2.5 w-fit max-w-[88%] rounded-2xl rounded-bl-sm bg-accent/12 px-3.5 py-2 text-sm">
          Tech is up 8% this week on strong earnings. Given your moderate risk profile, a small
          add fits — here's the data behind it.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {["yfinance", "NewsAPI", "Fear & Greed"].map((c) => (
            <span
              key={c}
              className="inline-flex items-center gap-1 rounded-full border border-line bg-bg/60 px-2.5 py-1 text-xs text-content-muted"
            >
              <ShieldCheck className="h-3 w-3 text-accent" />
              {c}
            </span>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-2xl">
      <div className="flex items-center gap-3 rounded-xl border border-line bg-bg/50 p-3">
        <FileText className="h-8 w-8 shrink-0 text-loss" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">statement_may.pdf</p>
          <p className="text-xs text-content-muted">Processed · 38 transactions</p>
        </div>
        <Check className="ml-auto h-5 w-5 shrink-0 text-accent" />
      </div>
      <div className="mt-3 space-y-2">
        {[
          ["Migros", "Groceries", "-₺842"],
          ["Spotify", "Subscriptions", "-₺59"],
          ["Salary", "Income", "+₺28,400"],
        ].map(([name, cat, amt]) => (
          <div key={name} className="flex items-center justify-between rounded-lg bg-surface-raised px-3 py-2 text-sm">
            <span className="font-medium">{name}</span>
            <span className="text-xs text-content-muted">{cat}</span>
            <span className={`font-mono ${amt.startsWith("+") ? "text-gain" : "text-content"}`}>{amt}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * ShowcaseSection — pinned scroll-scrub on desktop, classic stacked rows on
 * mobile / reduced motion. While the tall wrapper scrolls, the inner screen
 * stays pinned and scrolling scrubs between slides: the outgoing mock swings
 * away in 3D while the next one swings in.
 */
function ShowcaseSection() {
  const { t } = useTranslation("landing");
  const rows = t("showcase.rows", { returnObjects: true }) as unknown as ShowRow[];
  const reduce = useReducedMotion();
  const desktop = useMediaQuery("(min-width: 1024px)");
  if (reduce || !desktop || rows.length < 2) return <StackedShowcase rows={rows} />;
  return <ScrubShowcase rows={rows} />;
}

function ShowcaseCopy({ row, index, total }: { row: ShowRow; index: number; total: number }) {
  return (
    <div>
      <span className="num text-caption text-content-muted">
        {String(index + 1).padStart(2, "0")} / {String(total).padStart(2, "0")}
      </span>
      <p className="mt-2 text-overline uppercase text-accent">{row.eyebrow}</p>
      <h3 className="mt-3 font-display text-h1 font-bold tracking-tight">{row.title}</h3>
      <p className="mt-3 text-body text-content-muted">{row.desc}</p>
      <ul className="mt-5 space-y-2.5">
        {row.bullets.map((b) => (
          <li key={b} className="flex items-start gap-2.5 text-body-sm">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
              <Check className="h-3 w-3" />
            </span>
            {b}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StackedShowcase({ rows }: { rows: ShowRow[] }) {
  return (
    <section className="px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-20">
        {rows.map((r, i) => {
          const flip = i % 2 === 1;
          return (
            <div key={r.title} className="grid items-center gap-10 lg:grid-cols-2">
              <Reveal className={flip ? "lg:order-2" : ""}>
                <ShowcaseCopy row={r} index={i} total={rows.length} />
              </Reveal>
              <Reveal delay={0.1} className={flip ? "lg:order-1" : ""}>
                <ShowcaseMock index={i} />
              </Reveal>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ScrubShowcase({ rows }: { rows: ShowRow[] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const progress = useElementProgress(wrapRef);
  return (
    <section className="px-4 sm:px-6 lg:px-8">
      {/* Tall wrapper provides the scroll runway; the screen inside stays pinned. */}
      <div ref={wrapRef} className="relative" style={{ height: `${rows.length * 90 + 100}vh` }}>
        <div className="sticky top-0 flex h-screen items-center overflow-hidden">
          <div className="relative mx-auto h-[34rem] w-full max-w-6xl">
            {rows.map((r, i) => (
              <ScrubSlide key={r.title} row={r} index={i} total={rows.length} progress={progress} />
            ))}
            <div className="absolute -right-1 top-1/2 flex -translate-y-1/2 flex-col gap-2.5 xl:-right-8">
              {rows.map((_, i) => (
                <ScrubDot key={i} index={i} total={rows.length} progress={progress} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ScrubSlide({
  row,
  index,
  total,
  progress,
}: {
  row: ShowRow;
  index: number;
  total: number;
  progress: MotionValue<number>;
}) {
  const seg = 1 / total;
  const start = index * seg;
  const end = start + seg;
  const fade = seg * 0.22;
  const first = index === 0;
  const last = index === total - 1;

  const opacity = useTransform(
    progress,
    first ? [end - fade, end] : last ? [start, start + fade] : [start, start + fade, end - fade, end],
    first ? [1, 0] : last ? [0, 1] : [0, 1, 1, 0],
  );
  const x = useTransform(progress, [start, end], [first ? 0 : 90, last ? 0 : -90]);
  const rotateY = useTransform(progress, [start, end], [first ? 0 : 18, last ? 0 : -18]);
  const pointerEvents = useTransform(opacity, (o) => (o > 0.5 ? "auto" : "none"));
  const flip = index % 2 === 1;

  return (
    <motion.div
      style={{ opacity, x, pointerEvents }}
      className="absolute inset-0 flex items-center"
    >
      <div className="grid w-full items-center gap-10 lg:grid-cols-2" style={{ perspective: "1200px" }}>
        <div className={flip ? "lg:order-2" : ""}>
          <ShowcaseCopy row={row} index={index} total={total} />
        </div>
        <motion.div style={{ rotateY }} className={flip ? "lg:order-1" : ""}>
          <ShowcaseMock index={index} />
        </motion.div>
      </div>
    </motion.div>
  );
}

function ScrubDot({
  index,
  total,
  progress,
}: {
  index: number;
  total: number;
  progress: MotionValue<number>;
}) {
  const seg = 1 / total;
  const start = index * seg;
  const end = start + seg;
  const opacity = useTransform(progress, [start - 0.001, start, end, end + 0.001], [0.25, 1, 1, 0.25]);
  const scale = useTransform(progress, [start, (start + end) / 2, end], [1, 1.5, 1]);
  return <motion.span style={{ opacity, scale }} className="h-2 w-2 rounded-full bg-accent" />;
}

/* ─────────────────────── Testimonials ────────────────────── */
function TestimonialsSection() {
  const { t } = useTranslation("landing");
  const items = t("testimonials.items", { returnObjects: true }) as unknown as Testi[];
  return (
    <section className="border-y border-line bg-surface/30 px-4 py-20 sm:px-6 lg:px-8">
      <SectionHeading eyebrow={t("testimonials.eyebrow")} title={t("testimonials.title")} />
      <div className="mx-auto mt-14 grid max-w-6xl gap-5 md:grid-cols-3">
        {items.map((it, i) => (
          <Reveal key={it.name} delay={i * 0.08}>
            <figure className="glass flex h-full flex-col rounded-2xl p-6">
              <div className="flex gap-0.5 text-warning">
                {Array.from({ length: 5 }).map((_, s) => (
                  <Star key={s} className="h-4 w-4 fill-current" />
                ))}
              </div>
              <blockquote className="mt-4 flex-1 text-body-sm text-content">"{it.quote}"</blockquote>
              <figcaption className="mt-5 flex items-center gap-3 border-t border-line pt-4">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/15 text-sm font-semibold text-accent">
                  {it.name.charAt(0)}
                </span>
                <span>
                  <span className="block text-sm font-semibold">{it.name}</span>
                  <span className="block text-xs text-content-muted">{it.role}</span>
                </span>
              </figcaption>
            </figure>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* ───────────────────────── Pricing ───────────────────────── */
function PricingSection({
  onRegister,
  onContact,
}: {
  onRegister: () => void;
  onContact: () => void;
}) {
  const { t } = useTranslation("landing");
  const tiers = t("pricing.tiers", { returnObjects: true }) as unknown as Tier[];
  return (
    <section id="pricing" className="scroll-mt-24 px-4 py-20 sm:px-6 lg:px-8">
      <SectionHeading
        eyebrow={t("pricing.eyebrow")}
        title={t("pricing.title")}
        subtitle={t("pricing.subtitle")}
      />
      <div className="mx-auto mt-14 grid max-w-5xl items-start gap-6 md:grid-cols-3">
        {tiers.map((tier, i) => (
          <Reveal key={tier.name} delay={i * 0.08} className="h-full">
            <TiltCard maxTilt={3} className="h-full">
            <div
              className={`relative flex h-full flex-col rounded-2xl border p-6 backdrop-blur-md ${
                tier.featured
                  ? "border-accent/60 bg-surface/80 shadow-card-hover ring-1 ring-accent/30"
                  : "border-line bg-surface/70"
              }`}
            >
              {tier.badge && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-1 text-overline uppercase text-white shadow-glow">
                  {tier.badge}
                </span>
              )}
              <h3 className="text-h4 font-semibold">{tier.name}</h3>
              <div className="mt-3 flex items-baseline gap-1.5">
                <span className="font-mono text-3xl font-bold tracking-tight">{tier.price}</span>
                {tier.period && <span className="text-caption text-content-muted">{tier.period}</span>}
              </div>
              <p className="mt-2 text-body-sm text-content-muted">{tier.desc}</p>
              <ul className="mt-5 flex-1 space-y-3">
                {tier.features.map((f) => (
                  <li key={f} className="flex items-start gap-2.5 text-body-sm">
                    <span
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                        tier.featured ? "bg-accent text-white" : "bg-accent/15 text-accent"
                      }`}
                    >
                      <Check className="h-3 w-3" />
                    </span>
                    {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={tier.featured ? onRegister : onContact}
                className={`mt-6 inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-3 text-sm font-semibold transition ${
                  tier.featured
                    ? "bg-accent text-white shadow-glow hover:opacity-90"
                    : "border border-line text-content hover:bg-surface-raised"
                }`}
              >
                {tier.cta}
                {tier.featured && <ArrowRight className="h-4 w-4" />}
              </button>
            </div>
            </TiltCard>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* ───────────────────────── Final CTA ─────────────────────── */
function FinalCTASection({
  onRegister,
  onDemo,
  demoLoading,
}: {
  onRegister: () => void;
  onDemo: () => void;
  demoLoading: boolean;
}) {
  const { t } = useTranslation("landing");
  return (
    <section className="px-4 py-20 sm:px-6 lg:px-8">
      <Reveal>
        <div className="glass-strong relative mx-auto max-w-5xl overflow-hidden rounded-3xl px-6 py-16 text-center">
          <div className="animate-aurora pointer-events-none absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-accent/25 blur-[120px]" />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl font-display text-h1 font-bold tracking-tight md:text-display">
              {t("cta.title")}
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-body text-content-muted">{t("cta.subtitle")}</p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <button
                onClick={onRegister}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-6 py-3.5 text-sm font-semibold text-white shadow-glow transition hover:opacity-90 sm:w-auto"
              >
                {t("cta.primary")}
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </button>
              <button
                onClick={onDemo}
                disabled={demoLoading}
                aria-busy={demoLoading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-line bg-bg px-6 py-3.5 text-sm font-semibold text-content transition hover:bg-surface-raised disabled:opacity-60 sm:w-auto"
              >
                {demoLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
                ) : (
                  <Sparkles className="h-4 w-4 text-accent" />
                )}
                {demoLoading ? t("cta.demoLoading") : t("cta.demo")}
              </button>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

/* ───────────────────────── Footer ────────────────────────── */
function LandingFooter({
  lang,
  onLang,
  onNav,
}: {
  lang: SupportedLanguage;
  onLang: (l: SupportedLanguage) => void;
  onNav: (id: string) => void;
}) {
  const { t } = useTranslation("landing");
  const { t: tc } = useTranslation("common");
  const L = (k: string) => t(`footer.links.${k}` as "footer.links.features");

  return (
    <footer id="contact" className="scroll-mt-24 border-t border-line bg-surface/40 px-4 pb-10 pt-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-10 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
          {/* brand + contact */}
          <div>
            <Wordmark />
            <p className="mt-4 max-w-xs text-body-sm text-content-muted">{t("footer.tagline")}</p>
            <div className="mt-5">
              <p className="text-sm font-semibold">{t("footer.contactTitle")}</p>
              <p className="mt-1 max-w-xs text-caption text-content-muted">{t("footer.contactDesc")}</p>
              <a
                href="mailto:hello@fincoach.app"
                className="mt-3 inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-content transition hover:border-accent/40 hover:text-accent"
              >
                <Mail className="h-4 w-4" />
                hello@fincoach.app
              </a>
            </div>
          </div>

          {/* product */}
          <div>
            <p className="text-overline uppercase text-content-muted">{t("footer.columns.product")}</p>
            <ul className="mt-4 space-y-2.5 text-body-sm">
              <li><button onClick={() => onNav("features")} className="text-content-muted transition hover:text-content">{L("features")}</button></li>
              <li><button onClick={() => onNav("pricing")} className="text-content-muted transition hover:text-content">{L("pricing")}</button></li>
              <li><button onClick={() => onNav("how")} className="text-content-muted transition hover:text-content">{L("demo")}</button></li>
              <li><button onClick={() => onNav("features")} className="text-content-muted transition hover:text-content">{L("coach")}</button></li>
            </ul>
          </div>

          {/* company */}
          <div>
            <p className="text-overline uppercase text-content-muted">{t("footer.columns.company")}</p>
            <ul className="mt-4 space-y-2.5 text-body-sm">
              <li><button onClick={() => onNav("how")} className="text-content-muted transition hover:text-content">{L("about")}</button></li>
              <li><a href="mailto:hello@fincoach.app" className="text-content-muted transition hover:text-content">{L("contact")}</a></li>
            </ul>
          </div>

          {/* legal */}
          <div>
            <p className="text-overline uppercase text-content-muted">{t("footer.columns.legal")}</p>
            <ul className="mt-4 space-y-2.5 text-body-sm">
              <li><span className="text-content-muted">{L("privacy")}</span></li>
              <li><span className="text-content-muted">{L("terms")}</span></li>
              <li><span className="text-content-muted">{L("disclaimer")}</span></li>
            </ul>
          </div>
        </div>

        <div className="mt-12 rounded-xl border border-line bg-bg/50 px-4 py-3 text-center text-caption text-content-muted">
          {tc("disclaimer")}
        </div>

        <div className="mt-6 flex flex-col items-center justify-between gap-4 border-t border-line pt-6 sm:flex-row">
          <p className="text-caption text-content-muted">
            © {new Date().getFullYear()} FinCoach. {t("footer.rights")}
          </p>
          <div className="flex items-center gap-2">
            <span className="text-caption text-content-muted">{t("footer.madeWith")}</span>
            <span className="mx-1 text-line">·</span>
            {(["tr", "en"] as const).map((l) => (
              <button
                key={l}
                onClick={() => onLang(l)}
                className={`rounded-md px-2 py-1 text-xs font-medium transition ${
                  lang === l ? "text-accent" : "text-content-muted hover:text-content"
                }`}
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}

/* ─────────────────────── Page shell ──────────────────────── */
export function LandingPage() {
  const { i18n } = useTranslation();
  const reduce = useReducedMotion();
  const navigate = useNavigate();
  const location = useLocation();
  const setUser = useAuthStore((s) => s.setUser);
  const [demoLoading, setDemoLoading] = useState(false);

  // Page-level scroll-parallax for the ambient background: the aurora blobs
  // drift at opposing rates and the WebGL field fades out past the hero.
  const scrollY = useScrollY();
  const blobAY = useTransform(scrollY, [0, 1400], [0, 220]);
  const blobBY = useTransform(scrollY, [0, 1400], [0, -160]);
  const canvas3dOpacity = useTransform(scrollY, [0, 700], [0.9, 0.28]);

  const lang: SupportedLanguage = getLanguageFromPath(location.pathname) ?? "en";

  const goLogin = () => navigate(buildLocalizedPath(lang, "/login"));
  const goRegister = () => navigate(buildLocalizedPath(lang, "/register"));
  const goContact = () => scrollToId("contact", !reduce);

  function handleLang(next: SupportedLanguage) {
    void i18n.changeLanguage(next);
    navigate(`/${next}`, { replace: true });
  }

  async function handleDemo() {
    if (demoLoading) return;
    setDemoLoading(true);
    const warmup = setTimeout(
      () => toast.info(lang === "tr" ? "Sunucu hazırlanıyor, lütfen bekleyin…" : "Warming up the server…"),
      6000,
    );
    try {
      const user = await loginDemo();
      setUser(user);
      toast.success(lang === "tr" ? "Demo hesabına giriş yapıldı." : "Signed in to the demo account.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Demo error";
      toast.error(msg);
    } finally {
      clearTimeout(warmup);
      setDemoLoading(false);
    }
  }

  return (
    <div className="relative min-h-dvh overflow-x-clip bg-bg text-content">
      {/* ambient background */}
      <div className="pointer-events-none fixed inset-0 -z-10" aria-hidden="true">
        <div className="landing-grid absolute inset-0 opacity-70" />
        {/* Parallax aurora: wrapper carries the scroll translate, inner keeps its drift. */}
        <motion.div style={reduce ? undefined : { y: blobAY }} className="absolute -left-24 -top-32">
          <div className="animate-aurora h-[34rem] w-[34rem] rounded-full bg-accent/20 blur-[130px]" />
        </motion.div>
        <motion.div style={reduce ? undefined : { y: blobBY }} className="absolute right-0 top-0">
          <div className="animate-aurora-slow h-[28rem] w-[28rem] rounded-full bg-emerald-400/10 blur-[130px]" />
        </motion.div>
        {/* WebGL constellation — mounted only when motion is allowed; fades past the hero. */}
        {!reduce && (
          <Suspense fallback={null}>
            <motion.div style={{ opacity: canvas3dOpacity }} className="absolute inset-0">
              <LandingBackground3D />
            </motion.div>
          </Suspense>
        )}
      </div>

      <ScrollProgressBar />
      <LandingNav lang={lang} onLang={handleLang} onLogin={goLogin} onRegister={goRegister} />

      <main>
        <Hero onRegister={goRegister} onDemo={handleDemo} demoLoading={demoLoading} />
        <TrustStrip />
        <StatsBand />
        <FeaturesSection />
        <HowSection />
        <ShowcaseSection />
        <TestimonialsSection />
        <PricingSection onRegister={goRegister} onContact={goContact} />
        <FinalCTASection onRegister={goRegister} onDemo={handleDemo} demoLoading={demoLoading} />
      </main>

      <LandingFooter lang={lang} onLang={handleLang} onNav={(id) => scrollToId(id, !reduce)} />
    </div>
  );
}
