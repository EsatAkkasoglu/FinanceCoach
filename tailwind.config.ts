import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

// Bridges a `--var` holding space-separated HSL channels (e.g. "224 14% 9%")
// into a Tailwind color that supports opacity modifiers: bg-surface, bg-surface/40.
const hslVar = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Brand: trustworthy green that pops on dark backgrounds.
        accent: {
          DEFAULT: "#1FB57A",
          fg: "#04130C",
          muted: "#0E3A2A",
        },
        // Semantic states
        gain: "#22C55E",
        loss: "#EF4444",
        warning: "#F59E0B",
        // Surface & text scale — single source of truth lives in index.css :root.
        // Maps HSL vars into real tokens: bg-surface / text-content-muted / border-line.
        bg: hslVar("bg"),
        surface: {
          DEFAULT: hslVar("surface"),
          raised: hslVar("surface-2"),
        },
        content: {
          DEFAULT: hslVar("text"),
          muted: hslVar("text-muted"),
        },
      },
      borderColor: {
        line: hslVar("border"),
      },
      divideColor: {
        line: hslVar("border"),
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        // Display face for hero headings / big numerals — geometric, modern fintech.
        display: ["Space Grotesk", "Inter", "system-ui", "sans-serif"],
      },
      // Named type scale (modular ~1.25). Use these semantic roles in new code
      // instead of ad-hoc text-[Npx] values. Tailwind's default sizes (xs/sm/…)
      // remain available for the existing codebase.
      fontSize: {
        display:   ["2.25rem",  { lineHeight: "1.1",  letterSpacing: "-0.02em", fontWeight: "700" }],
        h1:        ["1.875rem", { lineHeight: "1.2",  letterSpacing: "-0.02em", fontWeight: "600" }],
        h2:        ["1.5rem",   { lineHeight: "1.25", letterSpacing: "-0.01em", fontWeight: "600" }],
        h3:        ["1.25rem",  { lineHeight: "1.3",  fontWeight: "600" }],
        h4:        ["1rem",     { lineHeight: "1.4",  fontWeight: "600" }],
        body:      ["1rem",     { lineHeight: "1.6" }],
        "body-sm": ["0.875rem", { lineHeight: "1.5" }],
        caption:   ["0.75rem",  { lineHeight: "1.4" }],
        overline:  ["0.6875rem",{ lineHeight: "1.2", letterSpacing: "0.06em", fontWeight: "600" }],
      },
      borderRadius: {
        lg: "14px",   // inner elements (tiles, skeletons, buttons)
        xl: "18px",   // legacy / modals
        "2xl": "22px", // cards & hero — single canonical card radius
      },
      boxShadow: {
        glow: "0 0 24px -4px rgba(31, 181, 122, 0.45)",
        "glow-lg": "0 0 48px -8px rgba(31, 181, 122, 0.5), 0 0 120px -24px rgba(31, 181, 122, 0.35)",
        // Canonical card hover lift — replaces per-card inline shadow literals.
        "card-hover": "0 0 0 1px rgba(31, 181, 122, 0.15), 0 8px 24px rgba(0, 0, 0, 0.2)",
        // Frosted-glass elevation: deep drop + faint inner top highlight.
        glass: "0 8px 32px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.06)",
      },
      keyframes: {
        "agent-pulse": {
          "0%, 100%": { opacity: "0.7", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.05)" },
        },
        shimmer: {
          from: { backgroundPosition: "200% 0" },
          to: { backgroundPosition: "-200% 0" },
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 24px -4px rgba(31, 181, 122, 0.35)" },
          "50%": { boxShadow: "0 0 40px -4px rgba(31, 181, 122, 0.6)" },
        },
      },
      animation: {
        "agent-pulse": "agent-pulse 1.6s ease-in-out infinite",
        shimmer: "shimmer 2.4s linear infinite",
        "pulse-glow": "pulse-glow 3.2s ease-in-out infinite",
      },
    },
  },
  plugins: [typography],
} satisfies Config;
