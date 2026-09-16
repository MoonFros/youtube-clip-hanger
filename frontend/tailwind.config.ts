import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#08080d",
          900: "#0d0d15",
          850: "#12121d",
          800: "#171724",
          700: "#222234",
          600: "#2e2e44",
        },
        accent: {
          DEFAULT: "#8b5cf6",
          soft: "#a78bfa",
          dim: "#6d3fd6",
        },
        cy: "#22d3ee",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 24px rgba(139, 92, 246, 0.35)",
      },
    },
  },
  plugins: [],
};
export default config;
