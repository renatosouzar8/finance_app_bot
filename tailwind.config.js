/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}", // Garante que ele procure classes nos seus arquivos React
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
