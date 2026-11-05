import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// NextRole frontend dev server. Talks to the FastAPI backend over HTTP
// (scope.md Assumptions: React runs as a separate local web app).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
})
