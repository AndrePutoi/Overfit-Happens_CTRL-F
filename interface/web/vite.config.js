import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Em desenvolvimento (npm run dev), /api e /media vão para a API em localhost:8000.
// No Docker, o nginx faz o mesmo (ver nginx.conf).
const proxy = {
  '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
  '/media': { target: 'http://localhost:8000', changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
})
