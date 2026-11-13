import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Served at semtip.nl/koos, so everything lives under /koos/.
export default defineConfig({
  base: '/koos/',
  plugins: [react()],
  build: { outDir: 'dist/koos', emptyOutDir: true },
  server: {
    fs: { allow: ['..'] }, // example transcripts live in ../data
    proxy: { '/koos/api': 'http://localhost:8000' },
  },
})
