/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#070d1a", 900: "#0b1324", 850: "#0f1a2f", 800: "#13203a", 700: "#1b2b4b", 600: "#263a60", 500: "#3a5079" },
        mist: { 50: "#f3f6fb", 100: "#e3e9f3", 200: "#c6d1e3", 300: "#9fb0cb", 400: "#7d8fae", 500: "#5f7294" },
        gold: { 300: "#f6d58e", 400: "#f0c062", 500: "#e3a73a", 600: "#c48a22" },
        pass: { 400: "#5fd3a5", 500: "#34b885", 900: "#0f3a2c" },
        fail: { 400: "#ff8b7a", 500: "#f2654f", 900: "#47201b" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Consolas", "monospace"],
      },
      maxWidth: { read: "72ch" },
    },
  },
  plugins: [],
};
