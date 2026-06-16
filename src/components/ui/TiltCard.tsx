/**
 * TiltCard — pointer-tracked 3D tilt wrapper for cards.
 *
 * Wraps any card content in a perspective stage that tilts toward the cursor
 * (spring-smoothed, same feel as the landing HeroVisual) plus an optional
 * radial glare that follows the pointer. Pure CSS 3D — no WebGL — so it is
 * cheap enough for grids of KPI cards.
 *
 * Disabled entirely under prefers-reduced-motion and on touch (no mousemove).
 */
import { useRef, type ReactNode } from "react";
import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from "framer-motion";

interface Props {
  children: ReactNode;
  className?: string;
  /** Max tilt in degrees. Keep small (3–6) for dashboard cards. Default 4. */
  maxTilt?: number;
  /** Show the pointer-following glare highlight. Default true. */
  glare?: boolean;
}

export function TiltCard({ children, className, maxTilt = 4, glare = true }: Props) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);

  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const cfg = { stiffness: 220, damping: 22, mass: 0.4 };
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [maxTilt, -maxTilt]), cfg);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [-maxTilt, maxTilt]), cfg);
  const glareX = useTransform(px, [-0.5, 0.5], [15, 85]);
  const glareY = useTransform(py, [-0.5, 0.5], [15, 85]);
  const glareBg = useMotionTemplate`radial-gradient(360px circle at ${glareX}% ${glareY}%, rgba(255,255,255,0.07), transparent 65%)`;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (reduce) return;
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  }
  function onLeave() {
    px.set(0);
    py.set(0);
  }

  if (reduce) return <div className={className}>{children}</div>;

  return (
    <div style={{ perspective: "1000px" }} className={className}>
      <motion.div
        ref={ref}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        style={{ rotateX, rotateY, transformStyle: "preserve-3d" }}
        className="relative h-full"
      >
        {children}
        {glare && (
          <motion.div
            aria-hidden="true"
            style={{ background: glareBg }}
            className="pointer-events-none absolute inset-0 rounded-2xl"
          />
        )}
      </motion.div>
    </div>
  );
}
