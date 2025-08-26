import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true, // Allow external connections in dev mode
    hmr: {
      timeout: 5000,  // Збільшити таймаут HMR
      overlay: true  // Показувати помилки в overlay
    },
    sourcemapIgnoreList: false, // Не ігноруємо source maps
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, '/api'),  // Явний rewrite для уникнення помилок
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.error('🚨 API Proxy Error:', err.message);
            console.error('   URL:', req.url);
            console.error('   Target:', 'http://localhost:8000');
            // Якщо backend недоступний, повертаємо 503
            if (res && !res.headersSent) {
              res.writeHead(503, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ 
                error: 'Backend server unavailable',
                message: 'Backend сервер недоступний. Перевірте що він запущений на порту 8000.'
              }));
            }
          });
          proxy.on('proxyReq', (proxyReq, req, res) => {
            console.log('📤 Proxy API Request:', req.method, req.url);
          });
          proxy.on('proxyRes', (proxyRes, req, res) => {
            console.log('📥 Backend API Response:', proxyRes.statusCode, req.url);
          });
        }
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.error('🚨 WebSocket Proxy Error:', err.message);
            console.error('   Target:', 'ws://localhost:8000');
          });
          proxy.on('open', () => {
            console.log('🔌 WebSocket proxy connection opened');
          });
          proxy.on('close', () => {
            console.log('🔌 WebSocket proxy connection closed');
          });
        }
      }
    }
  },
  build: {
    outDir: 'build',
    sourcemap: true, // Зміна з 'inline' на true для генерації окремих .map файлів
    minify: 'esbuild',
    rollupOptions: {
      output: {
        sourcemapExcludeSources: false, // Включити джерела в source maps
      }
    }
  },
  esbuild: {
    sourcemap: true  // Зміна з 'inline' на true для esbuild
  },
  define: {
    // Фіксимо possible issues with global definitions
    global: 'globalThis',
  }
});
