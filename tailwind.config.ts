import type { Config } from "tailwindcss";

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
  plugins: [],
} satisfies Config;
