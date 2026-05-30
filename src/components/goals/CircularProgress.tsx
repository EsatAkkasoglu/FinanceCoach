/**
 * CircularProgress — clean animated SVG ring with milestone markers.
 */
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

interface Props {
  pct: number;
  size?: number;
  strokeWidth?: number;
  children?: React.ReactNode;
  completed?: boolean;
  className?: string;
}

const MILESTONES = [25, 50, 75];

// Angle measured clockwise from positive-x axis. The parent <svg> is rotated
// -90deg, so 0deg here renders at the top of the ring (the arc's start point).
function pointOnRing(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

export function CircularProgress({
  pct,
  size = 120,
  strokeWidth = 10,
  children,
  completed = false,
  className,
}: Props) {
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  const clamped = Math.min(Math.max(pct, 0), 100);
  const offset = circ * (1 - clamped / 100);

  const arcRef = useRef<SVGCircleElement>(null);

  // Animate from empty → target whenever offset changes (and on mount).
  useEffect(() => {
    const el = arcRef.current;
    if (!el) return;
    const raf = requestAnimationFrame(() => {
      el.style.transition = "stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)";
      el.style.strokeDashoffset = String(offset);
    });
    return () => cancelAnimationFrame(raf);
  }, [offset]);

  const trackColor = completed ? "#22c55e22" : "#ffffff12";
  const arcColor = completed
    ? "#22c55e"
    : clamped > 66 ? "#10b981"
    : clamped > 33 ? "#f59e0b"
    : "#6366f1";

  const dotR = Math.max(2.5, strokeWidth * 0.32);

  return (
    <div
      className={cn("relative shrink-0", className)}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: "rotate(-90deg)" }}
      >
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={trackColor}
          strokeWidth={strokeWidth}
        />

        {/* Progress arc */}
        <circle
          ref={arcRef}
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={arcColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ}
        />

        {/* Milestone dots */}
        {MILESTONES.map((m) => {
          const passed = clamped >= m;
          const { x, y } = pointOnRing(cx, cy, r, m * 3.6);
          return (
            <circle
              key={m}
              cx={x}
              cy={y}
              r={dotR}
              fill={passed ? arcColor : "#0d1117"}
              stroke={passed ? arcColor : "#ffffff20"}
              strokeWidth={1.25}
            />
          );
        })}
      </svg>

      {children && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {children}
        </div>
      )}
    </div>
  );
}
