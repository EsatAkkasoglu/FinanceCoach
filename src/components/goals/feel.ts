/**
 * feel.ts — Savings Quest "game feel" tokens.
 *
 * Single source of truth for the micro-interaction timing/easing used across
 * the Goals section, so every press / success / settle reads consistently.
 * Principles encoded: anticipation, follow-through, overshoot, settle.
 * Rule: direct UI feedback ≤ ~300ms; only celebratory follow-through runs longer.
 */
import type { Transition, Variants } from "framer-motion";

// ── Easing curves ─────────────────────────────────────────────────────────────
export const EASE = {
  out: [0.4, 0, 0.2, 1] as const,       // standard decel
  inOut: [0.45, 0, 0.55, 1] as const,
  // Overshoots target then settles — the signature "juice" curve.
  overshoot: [0.34, 1.56, 0.64, 1] as const,
};

// ── Springs ───────────────────────────────────────────────────────────────────
export const SPRING = {
  // Button release: snappy, slight overshoot.
  press: { type: "spring", stiffness: 520, damping: 18, mass: 0.6 } as Transition,
  // Milestone dot pop: bouncy reward punctuation.
  pop: { type: "spring", stiffness: 600, damping: 12 } as Transition,
  // Trophy / badge entrance.
  reward: { type: "spring", stiffness: 400, damping: 11 } as Transition,
  // Card entrance settle.
  settle: { type: "spring", stiffness: 260, damping: 22 } as Transition,
};

// ── Reusable variants ───────────────────────────────────────────────────────────

/** Card entrance — fade + rise + subtle scale-in, settling via spring. */
export const cardEntrance: Variants = {
  hidden: { opacity: 0, y: 20, scale: 0.97 },
  visible: { opacity: 1, y: 0, scale: 1, transition: SPRING.settle },
};

/** Press feedback for chips/buttons: squash on tap, spring back on release. */
export const pressable = {
  whileTap: { scale: 0.9 },
  transition: SPRING.press,
} as const;

/** Error shake — horizontal rejection wiggle (≤360ms). */
export const shake: Variants = {
  idle: { x: 0 },
  shake: {
    x: [0, -6, 6, -5, 5, -3, 0],
    transition: { duration: 0.36, ease: EASE.inOut },
  },
};

/** Floating "+amount" label that rises and fades after a contribution. */
export const floatLabel = {
  initial: { opacity: 1, y: 0, x: "-50%", scale: 0.8 },
  animate: { opacity: 0, y: -46, x: "-50%", scale: 1.05 },
  exit: { opacity: 0 },
  transition: { duration: 1.1, ease: EASE.out },
} as const;

// ── Coin-burst geometry ─────────────────────────────────────────────────────────
export interface CoinSpec {
  id: number;
  dx: number; // px horizontal travel
  dy: number; // px vertical travel (negative = up)
  rot: number;
  delay: number;
}

/** Generate N coins arcing outward+up from a center origin. */
export function makeCoins(n = 6): CoinSpec[] {
  return Array.from({ length: n }, (_, i) => {
    const spread = (i / (n - 1) - 0.5) * 2; // -1 .. 1
    return {
      id: i,
      dx: spread * (34 + Math.random() * 18),
      dy: -(38 + Math.random() * 30),
      rot: spread * 180 + (Math.random() * 60 - 30),
      delay: Math.random() * 0.05,
    };
  });
}
