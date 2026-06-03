import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Vazirmatn", "Inter", "system-ui", "sans-serif"],
        latin: ["Inter", "Vazirmatn", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        bg: { DEFAULT: "#07090d", 2: "#0b0f15" },
        surface: { DEFAULT: "#11161d", 2: "#181f2a", 3: "#232c3a" },
        border: { DEFAULT: "#232c38", strong: "#2f3a48" },
        text: { DEFAULT: "#eef2f8", dim: "#98a4b6", faint: "#65728a" },
        accent: { DEFAULT: "#2ee0c4", 2: "#6366f1", soft: "rgba(46,224,196,0.14)" },
        ok: { DEFAULT: "#34d399", soft: "rgba(52,211,153,0.18)" },
        warn: { DEFAULT: "#fbbf24", soft: "rgba(251,191,36,0.18)" },
        danger: { DEFAULT: "#f87171", soft: "rgba(248,113,113,0.18)" },
      },
      borderRadius: { lg: "16px", md: "10px" },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 6px 18px rgba(0,0,0,0.18)",
        pop: "0 12px 32px rgba(0,0,0,0.32)",
      },
      transitionTimingFunction: { swift: "cubic-bezier(0.32, 0.72, 0, 1)" },
    },
  },
  plugins: [],
};

export default config;
