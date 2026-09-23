import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function gitHash(): string {
  try {
    return execSync('git rev-parse --short HEAD').toString().trim()
  } catch {
    return 'dev'
  }
}

// dev: vite :5173, /api 代理到后端 :8686；build 后由 preview 或任意静态服务托管
export default defineConfig({
  plugins: [react()],
  define: { __GIT_HASH__: JSON.stringify(gitHash()) },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8686',
    },
  },
})
