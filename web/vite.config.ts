import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // mock-файлы лежат в ../docs/mock, метрики — в ../core/reports
    fs: { allow: ['..'] },
    proxy: { '/api': { target: process.env.API_URL ?? 'http://localhost:8000', changeOrigin: true } },
  },
})
