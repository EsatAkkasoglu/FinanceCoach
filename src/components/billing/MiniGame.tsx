/**
 * Minimalist coin-tap reflex game. Self-contained, no deps beyond framer-motion,
 * respects reduced motion, keeps a best score in localStorage. Tap the accent
 * coins before they fade. 20-second round.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Coins } from "lucide-react";

type Phase = "idle" | "playing" | "over";
interface Coin {
  id: number;
  x: number; // %
  y: number; // %
  expires: number;
}

const DURATION = 20_000;
const SPAWN_EVERY = 650;
const COIN_LIFE = 1150;
const MAX_COINS = 5;
const BEST_KEY = "fincoach-game-best";

export function MiniGame() {
  const { t } = useTranslation("billing");
  const reduce = useReducedMotion();

  const [phase, setPhase] = useState<Phase>("idle");
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(DURATION / 1000);
  const [coins, setCoins] = useState<Coin[]>([]);
  const [best, setBest] = useState(0);
  const idRef = useRef(0);

  useEffect(() => {
    const stored = Number(localStorage.getItem(BEST_KEY) || 0);
    if (!Number.isNaN(stored)) setBest(stored);
  }, []);

  // Game engine — one interval prunes expired coins, spawns new ones, and ticks
  // the clock. Runs only while playing; fully torn down otherwise.
  useEffect(() => {
    if (phase !== "playing") return;
    const start = performance.now();
    let lastSpawn = 0;
    const tick = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - start;
      setTimeLeft(Math.max(0, Math.ceil((DURATION - elapsed) / 1000)));
      setCoins((cs) => cs.filter((c) => c.expires > now));
      if (now - lastSpawn >= SPAWN_EVERY) {
        lastSpawn = now;
        setCoins((cs) =>
          cs.length >= MAX_COINS
            ? cs
            : [
                ...cs,
                {
                  id: ++idRef.current,
                  x: 8 + Math.random() * 82,
                  y: 14 + Math.random() * 70,
                  expires: now + COIN_LIFE,
                },
              ],
        );
      }
      if (elapsed >= DURATION) {
        window.clearInterval(tick);
        setCoins([]);
        setPhase("over");
      }
    }, 100);
    return () => window.clearInterval(tick);
  }, [phase]);

  // Persist best when a round ends.
  useEffect(() => {
    if (phase !== "over") return;
    setBest((b) => {
      const next = Math.max(b, score);
      localStorage.setItem(BEST_KEY, String(next));
      return next;
    });
  }, [phase, score]);

  function startGame() {
    setScore(0);
    setTimeLeft(DURATION / 1000);
    setCoins([]);
    setPhase("playing");
  }

  function grab(id: number) {
    setScore((s) => s + 1);
    setCoins((cs) => cs.filter((c) => c.id !== id));
  }

  return (
    <div className="mx-auto mt-10 w-full max-w-md">
      <div className="mb-3 flex items-center justify-between text-caption text-content-muted">
        <span className="inline-flex items-center gap-1.5">
          <Coins className="h-4 w-4 text-accent" />
          {t("game.title")}
        </span>
        <span className="tabular-nums">
          {t("game.best")}: <span className="font-semibold text-content">{best}</span>
        </span>
      </div>

      <div className="relative h-72 overflow-hidden rounded-2xl border border-line bg-surface/60 backdrop-blur-sm">
        {/* HUD */}
        {phase === "playing" && (
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between px-4 py-2.5 text-caption">
            <span className="rounded-full bg-bg/70 px-2.5 py-1 font-semibold tabular-nums">
              {t("game.score")}: {score}
            </span>
            <span className="rounded-full bg-bg/70 px-2.5 py-1 tabular-nums text-content-muted">
              {timeLeft}s
            </span>
          </div>
        )}

        {/* Coins */}
        <AnimatePresence>
          {coins.map((c) => (
            <motion.button
              key={c.id}
              onClick={() => grab(c.id)}
              initial={reduce ? false : { scale: 0, opacity: 0 }}
              animate={reduce ? {} : { scale: 1, opacity: 1 }}
              exit={reduce ? {} : { scale: 0, opacity: 0 }}
              transition={{ duration: 0.12 }}
              style={{ left: `${c.x}%`, top: `${c.y}%` }}
              aria-label="coin"
              className="absolute -translate-x-1/2 -translate-y-1/2"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-white shadow-glow ring-2 ring-accent/30 transition-transform active:scale-90">
                <Coins className="h-4 w-4" />
              </span>
            </motion.button>
          ))}
        </AnimatePresence>

        {/* Idle / Over overlay */}
        {phase !== "playing" && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-bg/40 px-6 text-center backdrop-blur-[2px]">
            {phase === "over" && (
              <p className="text-sm font-semibold">
                {t("game.gameOver")} · {t("game.score")}: {score}
                {score >= best && score > 0 ? ` · ${t("game.newBest")} 🎉` : ""}
              </p>
            )}
            {phase === "idle" && (
              <p className="max-w-xs text-caption text-content-muted">{t("game.subtitle")}</p>
            )}
            <button
              onClick={startGame}
              className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-glow transition hover:opacity-90"
            >
              <Coins className="h-4 w-4" />
              {phase === "over" ? t("game.restart") : t("game.start")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
