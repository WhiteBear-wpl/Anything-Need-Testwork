import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// UI 自动化测试通过 VITE_API_TARGET 指向隔离的测试后端
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': apiTarget,
    },
  },
});
