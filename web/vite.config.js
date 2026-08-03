import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const rootDir = fileURLToPath(new URL('.', import.meta.url))
const distDir = fileURLToPath(new URL('../frontend/dist', import.meta.url))

// 构建产物输出到 frontend/dist，由 FastAPI 静态托管
export default defineConfig({
  plugins: [vue()],
  base: '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: distDir,
    // 暂时关闭自动清空目录，避免 trash 钩子导致的构建失败。
    // 手动清理或后续恢复为 true。
    emptyOutDir: false,
    assetsDir: 'assets',
    chunkSizeWarningLimit: 1200,
  },
})
