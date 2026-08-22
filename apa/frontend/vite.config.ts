import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// dev: /api 代理到 Python serve，免除 CORS；build: 同源产物供 Electron 加载
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8686", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
