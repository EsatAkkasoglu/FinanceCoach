/**
 * Juice.tsx — celebratory follow-through effects for the Savings Quest.
 *
 * CoinBurst   — coins arc out from a contribution origin (overshoot + follow-through).
 * Confetti    — one-shot burst when a goal completes.
 * Odometer    — animated rolling number for contributed amounts.
 *
 * All effects are pointer-events-none and self-clean; they never block input.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { Coins } from "lucide-react";
import { EASE, makeCoins } from "./feel";

// ── Coin burst ──────────────────────────────────────────────────────────────────
export function CoinBurst({ fireKey }: { fireKey: number | null }) {
  const coins = useMemo(() => makeCoins(6), [fireKey]);
  if (fireKey == null) return null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-1/2 z-20" aria-hidden="true">
      <AnimatePresence>
        {coins.map((c) => (
          <motion.span
            key={`${fireKey}-${c.id}`}
            initial={{ opacity: 0, x: 0, y: 0, scale: 0.4, rotate: 0 }}
            animate={{
              opacity: [0, 1, 1, 0],
              x: c.dx,
              y: [0, c.dy, c.dy + 14],
              scale: [0.4, 1, 0.9],
              rotate: c.rot,
            }}
            transition={{ duration: 0.65, ease: EASE.out, delay: c.delay, times: [0, 0.3, 0.7, 1] }}
            className="absolute -translate-x-1/2 -translate-y-1/2 text-warning"
          >
            <Coins className="h-3.5 w-3.5 drop-shadow-[0_0_4px_rgba(245,158,11,0.7)]" />
          </motion.span>
        ))}
      </AnimatePresence>
    </div>
  );
}

// ── Confetti (goal complete) ──────────────────────────────────────────────────────
const CONFETTI_COLORS = ["#22c55e", "#10b981", "#f59e0b", "#fbbf24", "#34d399"];

export function Confetti({ fire }: { fire: boolean }) {
  const [pieces, setPieces] = useState<number[]>([]);
  useEffect(() => {
    if (!fire) return;
    setPieces(Array.from({ length: 28 }, (_, i) => i));
    const t = setTimeout(() => setPieces([]), 1300);
    return () => clearTimeout(t);
  }, [fire]);

  return (
    <div className="pointer-events-none absolute inset-0 z-30 overflow-hidden" aria-hidden="true">
      <AnimatePresence>
        {pieces.map((i) => {
          const dx = (Math.random() - 0.5) * 280;
          const dur = 0.9 + Math.random() * 0.4;
          return (
            <motion.span
              key={i}
              initial={{ opacity: 1, x: 0, y: 0, rotate: 0 }}
              animate={{ opacity: [1, 1, 0], x: dx, y: 220 + Math.random() * 80, rotate: Math.random() * 540 }}
              transition={{ duration: dur, ease: EASE.out, times: [0, 0.7, 1] }}
              className="absolute left-1/2 top-6 h-2 w-1.5 rounded-[1px]"
              style={{ backgroundColor: CONFETTI_COLORS[i % CONFETTI_COLORS.length] }}
            />
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// ── Odometer number ───────────────────────────────────────────────────────────────
export function Odometer({ value, format }: { value: number; format: (n: number) => string }) {
  const [display, setDisplay] = useState(value);
  useEffect(() => {
    const from = display;
    const to = value;
    if (from === to) return;
    const start = performance.now();
    const dur = 600;
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(from + (to - from) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return <span className="tabular-nums">{format(display)}</span>;
}
