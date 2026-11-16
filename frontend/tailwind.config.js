/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          darkest: "#0B0E14",
          card: "#121824",
          border: "#1E293B",
          accent: "#2563EB",
          accentHover: "#1D4ED8",
          bullish: "#10B981",
          bearish: "#EF4444",
          warning: "#F59E0B",
          neutral: "#94A3B8",
        },
      },
    },
  },
  plugins: [],
};

