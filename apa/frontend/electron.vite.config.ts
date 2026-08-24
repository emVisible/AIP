import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

/**
 * electron-vite 统一配置 —— main / preload / renderer 三进程。
 *
 * renderer 段继承原 vite.config.ts（React + Tailwind + /api proxy）；
 * dev 模式下 proxy 把 /api/* 转发到 Python serve，设计器目录正常加载。
 */
export default defineConfig({
  // ---- 主进程（TypeScript）----
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "out/main",
      lib: {
        entry: resolve(__dirname, "src/main/index.ts"),
      },
    },
  },

  // ---- Preload 安全桥（TypeScript）----
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: "out/preload",
      lib: {
        entry: resolve(__dirname, "src/preload/index.ts"),
      },
    },
  },

  // ---- 渲染器（React SPA）----
  renderer: {
    root: ".",
    plugins: [react(), tailwindcss()],
    build: {
      outDir: "dist",
      rollupOptions: {
        input: resolve(__dirname, "index.html"),
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: "http://127.0.0.1:8686", changeOrigin: true },
      },
    },
  },
});
