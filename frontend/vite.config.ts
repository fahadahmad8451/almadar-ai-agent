import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Al Madar Holding — Enterprise AI Agent (Setup v0.1)
// Dev proxy: /api -> FastAPI, so the browser never hard-codes a host.
// The API target comes from AMH_API_TARGET (default: dev API on :8100).
// Staging preview runs with AMH_API_TARGET=http://127.0.0.1:8101, so the
// same build serves both envs — only the proxy target differs, and the
// browser still talks to one origin (cookies stay first-party).
const apiTarget = process.env.AMH_API_TARGET || 'http://127.0.0.1:8100'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3100,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 3100,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
