/**
 * APA Desktop 主进程 —— 窗口先行，sidecar 异步就绪。
 *
 * 核心原则：窗口永远先创建（用户看到东西），
 *           后端服务异步启动（数据渐进加载）。
 *
 * 双模式：
 *   dev  → .venv python + vite HMR(localhost:5173) + /api proxy
 *   packaged → Resources/apa-server 冻结二进制 + userData 可写目录
 */
import { app, BrowserWindow, ipcMain, screen } from "electron";
import { spawn, type ChildProcess } from "child_process";
import fs from "fs";
import path from "path";
import net from "net";

import { IpcChannels } from "../shared/ipc-types";

const isDev = !app.isPackaged;
const VITE_PORT = 5173;

// ---- 布局 ---------------------------------------------------------------------

interface Layout {
  apaDir: string;
  venvPy?: string;
  serverBin?: string;
  processesDir: string;
  journalGlob: string;
  logFile: string;
  cwd: string;
}

function resolveLayout(): Layout {
  if (isDev) {
    // __dirname = <frontend>/out/main → 上三级 = apa/
    const apaDir = path.resolve(__dirname, "..", "..", "..");
    return {
      apaDir,
      venvPy: path.join(apaDir, ".venv", "bin", "python"),
      processesDir: path.join(apaDir, "data", "processes"),
      journalGlob: path.join(apaDir, "data", "*.jsonl"),
      logFile: path.join(apaDir, "serve.log"),
      cwd: apaDir,
    };
  }
  const rt = path.join(process.resourcesPath, "apa-server");
  const userData = app.getPath("userData");
  fs.mkdirSync(path.join(userData, "processes"), { recursive: true });
  fs.mkdirSync(path.join(userData, "journals"), { recursive: true });
  return {
    apaDir: rt,
    serverBin: rt,
    processesDir: path.join(userData, "processes"),
    journalGlob: path.join(userData, "journals", "*.jsonl"),
    logFile: path.join(userData, "serve.log"),
    cwd: userData,
  };
}

let pythonProc: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;

// ---- 工具 -------------------------------------------------------------------

function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, () => {
      const port = (srv.address() as { port: number }).port;
      srv.close(() => resolve(port));
    });
  });
}

function waitHealthy(port: number, timeoutMs = 20_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const poll = (): void => {
      fetch(`http://127.0.0.1:${port}/api/processes`)
        .then((r) => resolve(r.ok))
        .catch(() => {
          if (Date.now() < deadline) setTimeout(poll, 500);
          else resolve(false);
        });
    };
    poll();
  });
}

// ---- Python sidecar -----------------------------------------------------------

async function startServe(port: number, L: Layout): Promise<boolean> {
  const isFrozen = !!L.serverBin;
  const bin = isFrozen
    ? path.join(L.serverBin ?? "", "apa_server")
    : L.venvPy ?? "";
  const args = isFrozen
    ? ["serve", "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir]
    : ["-m", "apa_core.cli", "serve",
       "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir];

  try {
    const logFd = fs.openSync(L.logFile, "a");
    pythonProc = spawn(bin, args, {
      cwd: L.cwd, stdio: ["ignore", logFd, logFd],
    });
  } catch (e) {
    console.error("[desktop] failed to spawn python:", e);
    return false;
  }

  const ok = await waitHealthy(port);
  if (ok) console.log(`[desktop] serve ready on :${port}`);
  else console.warn(`[desktop] serve health check timeout on :${port}`);
  return ok;
}

// ---- 窗口创建（永不失败——先给用户看东西）---------------------------------------

function createWindow(loadUrl?: string): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    title: "APA Desktop",
    show: true,                       // ← 立即可见
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "../preload/index.mjs"),
    },
  });

  if (loadUrl) {
    mainWindow.loadURL(loadUrl).catch(() => {
      // 加载失败显示空白页而不是白屏崩溃
      mainWindow?.loadURL(
        "data:text/html,<h2 style='font-family:sans-serif'>Loading…</h2>");
    });
  }
}

// ---- 主流程：窗口先行，sidecar 异步 ---------------------------------------------

async function main(): Promise<void> {
  const L = resolveLayout();

  // ① 立即创建窗口（用户先看到 UI）
  if (isDev) {
    createWindow(`http://localhost:${VITE_PORT}`);
  } else {
    createWindow();   // packaged 模式等 sidecar 就绪后再加载 URL
  }

  // ② 启动 Python sidecar（异步，不阻塞窗口）
  const port = await freePort();

  // dev 模式下把实际端口传给 vite proxy（通过环境变量）
  if (isDev) {
    process.env.APA_SERVE_PORT = String(port);
  }

  const healthy = await startServe(port, L);

  // ③ packaged 模式：sidecar 就绪后加载页面
  if (!isDev) {
    const url = healthy
      ? `http://127.0.0.1:${port}`
      : "data:text/html," +
        encodeURIComponent(
          "<h2 style='font-family:sans-serif;color:#999'>" +
          "Backend unavailable</h2>");
    mainWindow?.loadURL(url);
  }

  console.log(`[desktop] ready (healthy=${healthy}, port=${port})`);
}

// ---- 拾取器 overlay -----------------------------------------------------------

let overlayWin: BrowserWindow | null = null;

function ensureOverlay(): BrowserWindow {
  if (overlayWin && !overlayWin.isDestroyed()) return overlayWin;
  const disp = screen.getPrimaryDisplay();
  overlayWin = new BrowserWindow({
    x: disp.bounds.x, y: disp.bounds.y,
    width: disp.bounds.width, height: disp.bounds.height,
    transparent: true, frame: false,
    resizable: false, movable: false,
    fullscreenable: false, skipTaskbar: true,
    hasShadow: false, show: true, alwaysOnTop: true,
    webPreferences: { nodeIntegration: true, contextIsolation: false },
  });
  overlayWin.setIgnoreMouseEvents(true);
  overlayWin.loadFile(
    path.resolve(__dirname, "..", "..", "electron", "overlay.html"));
  return overlayWin;
}

function closeOverlay(): void {
  if (overlayWin && !overlayWin.isDestroyed()) overlayWin.destroy();
  overlayWin = null;
}

function setupSpyIpc(): void {
  ipcMain.on(IpcChannels.SpyOverlayShow, () => {
    try { ensureOverlay(); } catch (e) { console.error("[spy]", e); }
  });
  ipcMain.on(IpcChannels.SpyOverlayHide, () => closeOverlay());
  ipcMain.on(IpcChannels.SpyBounds, (_e, payload) => {
    if (overlayWin && !overlayWin.isDestroyed()) {
      overlayWin.webContents.send(IpcChannels.SpyBounds, payload);
    }
  });
}

// ---- IPC handlers（桌面应用 OS 能力入口）----------------------------------------

function setupOsIpc(): void {
  /** 打开原生文件选择对话框 */
  ipcMain.handle("os:pick-file", async (_, options?) => {
    const { dialog } = await import("electron");
    const result = await dialog.showOpenDialog({
      properties: ["openFile"],
      ...options,
    });
    return result.canceled ? null : result.filePaths[0];
  });

  /** 发送系统通知 */
  ipcMain.handle("os:notify", async (_, { title, body }) => {
    const { Notification } = await import("electron");
    new Notification({ title: title || "APA", body: body || "" }).show();
  });

  /** 获取系统信息（调试用） */
  ipcMain.handle("os:info", async () => ({
    platform: process.platform,
    arch: process.arch,
    electronVersion: process.versions.electron,
    nodeVersion: process.versions.node,
  }));
}

// ---- 生命周期 -------------------------------------------------------------------

app.whenReady().then(() => {
  setupSpyIpc();
  setupOsIpc();
  void main();
});

app.on("window-all-closed", () => {
  if (pythonProc) pythonProc.kill("SIGTERM");
  app.quit();
});
