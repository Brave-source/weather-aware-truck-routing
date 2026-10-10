import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // mapbox GL is isolated in a deferred map chunk, not the app's initial bundle.
  build: { chunkSizeWarningLimit: 2048 },
})
