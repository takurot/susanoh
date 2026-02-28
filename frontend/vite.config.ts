import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    exclude: ['tests/**', 'node_modules/**'],
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
