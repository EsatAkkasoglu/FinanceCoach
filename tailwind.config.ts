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
      },
      borderRadius: {
        lg: "14px",
        xl: "18px",
      },
      boxShadow: {
        glow: "0 0 24px -4px rgba(31, 181, 122, 0.45)",
      },
      keyframes: {
        "agent-pulse": {
          "0%, 100%": { opacity: "0.7", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.05)" },
        },
      },
      animation: {
        "agent-pulse": "agent-pulse 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [typography],
} satisfies Config;
