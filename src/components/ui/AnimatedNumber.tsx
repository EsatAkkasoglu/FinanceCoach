/**
 * AnimatedNumber — count-up via anime.js (v4).
 *
 * Demonstrates anime.js's JS-object tweening: we animate a plain `{ v }` object
 * and write the formatted value to the DOM in `onUpdate`. Coexists with the
 * app's framer-motion usage. Honors prefers-reduced-motion (renders the final
 * value with no animation) and animates from the previous value on updates.
 *
 * Uses useLayoutEffect to set the starting text before paint, so there's no
 * flash of the final value before the count-up begins.
 */
import { useLayoutEffect, useRef } from "react";
import { animate } from "animejs";
import { useReducedMotion } from "framer-motion";

export function AnimatedNumber({
  value,
  format = (v) => String(Math.round(v)),
  duration = 900,
  className,
}: {
  value: number;
  format?: (v: number) => string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduce = useReducedMotion();
  const from = useRef(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (reduce) {
      el.textContent = format(value);
      from.current = value;
      return;
    }

    const obj = { v: from.current };
    el.textContent = format(obj.v); // start frame, before paint — no flash
    const anim = animate(obj, {
      v: value,
      duration,
      ease: "outExpo",
      onUpdate: () => {
        el.textContent = format(obj.v);
      },
    });
    from.current = value;
    return () => {
      anim.cancel();
    };
  }, [value, duration, reduce, format]);

  return <span ref={ref} className={className} />;
}
