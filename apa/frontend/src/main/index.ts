/**
 * APA Desktop 主进程 —— Python sidecar 编排 + 窗口管理 + overlay IPC。
 *
 * 双模式：
 *   dev（!app.isPackaged）→ .venv python + 仓库资源
 *   packaged → Resources/apa-server 冻结二进制 + userData 可写目录
 */
import { app, BrowserWindow, ipcMain, screen } from "electron";
import { spawn, execSync, type ChildProcess } from "child_process";
import fs from "fs";
import path from "path";
import net from "net";

import { IpcChannels } from "../shared/ipc-types";

const isDev = !app.isPackaged;

// ---- 布局解析 ---------------------------------------------------------------

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

function waitHealthy(port: number, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const poll = (): void => {
      fetch(`http://127.0.0.1:${port}/api/processes`)
        .then((r) => (r.ok ? resolve() : setTimeout(poll, 500)))
        .catch(() => setTimeout(poll, 500));
      if (Date.now() > deadline) reject(new Error("timeout"));
    };
    poll();
  });
}

// ---- Python sidecar -----------------------------------------------------------

async function startServe(port: number, L: Layout): Promise<void> {
  const isFrozen = !!L.serverBin;
  const bin = isFrozen
    ? (L.serverBin ? path.join(L.serverBin, "apa_server") : "")
    : L.venvPy ?? "";
  const args = isFrozen
    ? ["serve", "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir]
    : ["-m", "apa_core.cli", "serve",
       "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir,
       "--frontend-dist", path.join(__dirname, "..", "..", "dist")];

  const logFd = fs.openSync(L.logFile, "a");
  pythonProc = spawn(bin, args, {
    cwd: L.cwd, stdio: ["ignore", logFd, logFd],
  });

  await waitHealthy(port);
  console.log(`[desktop] serve ready on :${port}`);
}

// ---- 启动前置检查 -------------------------------------------------------------

function checkRuntime(L: Layout): boolean {
  try {
    if (isDev && L.venvPy) {
      execSync(`"${L.venvPy}" -c "import apa_core"`, { timeout: 10_000 });
    } else if (L.serverBin) {
      fs.accessSync(path.join(L.serverBin, "apa_server"),
                     fs.constants.X_OK);
    }
    return true;
  } catch {
    return false;
  }
}

// ---- 主入口 -------------------------------------------------------------------

async function main(): Promise<void> {
  const L = resolveLayout();

  if (!checkRuntime(L)) {
    console.error(
      "[desktop] server runtime not available.\n" +
      (isDev
        ? "         Run first: cd apa/frontend && pnpm setup"
        : "         Runtime missing — reinstall the application"));
    app.quit();
    return;
  }

  const port = await freePort();
  await startServe(port, L);

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    title: "APA Desktop",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "../preload/index.js"),
    },
  });

  // dev 模式加载 vite HMR；packaged 模式加载 Python serve 的 SPA
  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadURL(`http://127.0.0.1:${port}`);
  }

  mainWindow.on("closed", () => {
    if (pythonProc) pythonProc.kill("SIGTERM");
    pythonProc = null;
    mainWindow = null;
  });
}

// ---- 拾取器 overlay -----------------------------------------------------------

let overlayWin: BrowserWindow | null = null;

function ensureOverlay(): BrowserWindow {
  if (overlayWin && !overlayWin.isDestroyed()) return overlayWin;
  const disp = screen.getPrimaryDisplay();
  overlayWin = new BrowserWindow({
    x: disp.bounds.x,
    y: disp.bounds.y,
    width: disp.bounds.width,
    height: disp.bounds.height,
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    show: true,
    alwaysOnTop: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
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

// ---- 生命周期 -------------------------------------------------------------------

app.whenReady().then(() => {
  setupSpyIpc();
  void main();
});

app.on("window-all-closed", () => {
  if (pythonProc) pythonProc.kill("SIGTERM");
  app.quit();
});
