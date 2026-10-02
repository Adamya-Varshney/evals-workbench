/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so light and dark themes share class names.
// ink-* = surfaces (950 is the page), mist-* = text (50 is strongest), accent-* = brand.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const scale = (prefix, steps) => Object.fromEntries(steps.map((s) => [s, v(`${prefix}-${s}`)]));

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: scale("ink", [950, 900, 850, 800, 700, 600, 500]),
        mist: scale("mist", [50, 100, 200, 300, 400, 500]),
        accent: scale("accent", [300, 400, 500, 600]),
        pass: scale("pass", [400, 500, 900]),
        fail: scale("fail", [400, 500, 900]),
        warn: scale("warn", [400, 900]),
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Consolas", "monospace"],
      },
      fontSize: { xxs: ["11px", "15px"] },
      maxWidth: { read: "72ch" },
    },
  },
  plugins: [],
};
