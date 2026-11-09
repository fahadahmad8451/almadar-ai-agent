/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        emerald: {
          50: '#ecf5f1',
          100: '#d3e8df',
          200: '#a9d1bf',
          300: '#74b39c',
          400: '#3f937a',
          500: '#21795f',
          600: '#14614c',
          700: '#0f4e3d',
          800: '#0b3d2e',
          900: '#0b3d2e',
          950: '#072a20',
        },
        gold: {
          400: '#d6b25e',
          500: '#c8a24b',
          600: '#a8823a',
        },
        teal: {
          100: '#d9efee',
          700: '#0e7c7b',
          800: '#0b6362',
        },
      },
      fontFamily: {
        sans: ['Inter', '"IBM Plex Sans Arabic"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgb(11 61 46 / 0.06), 0 1px 3px 0 rgb(11 61 46 / 0.08)',
      },
    },
  },
  plugins: [],
}
