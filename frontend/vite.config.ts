import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // JSON API for the new frontend (Flask proxy layer)
      '/v2': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      // Direct SSE + task API from FastAPI via nginx (or directly in dev)
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // File downloads (Flask serves from filesystem)
      '/d': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output to static/dist so Flask can serve the built app
    outDir: './static/dist',
    emptyOutDir: true,
  },
});
