/**
 * APA Desktop — Electron 主进程。
 * 职责：Python serve sidecar 编排 + BrowserWindow 加载 React SPA。
 */
const { app, BrowserWindow } = require("electron");
const { spawn, execSync } = require("child_process");
const path = require("path");

const APA_DIR = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(APA_DIR, "..");
const VENV_PY = path.join(APA_DIR, ".venv", "bin", "python");
const isDev = !app.isPackaged;

let pythonProc = null;
let mainWindow = null;

function freePort() {
  return new Promise((resolve) => {
    const net = require("net");
    const srv = net.createServer();
    srv.listen(0, () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function waitHealthy(port, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const poll = () => {
      fetch(`http://127.0.0.1:${port}/api/processes`)
        .then(r => (r.ok ? resolve() : setTimeout(poll, 500)))
        .catch(() => setTimeout(poll, 500));
      if (Date.now() > deadline) reject(new Error("timeout"));
    };
    poll();
  });
}

async function startServe(port) {
  const fs = require("fs");
  const logFd = fs.openSync(path.join(APA_DIR, "serve.log"), "a");
  pythonProc = spawn(VENV_PY,
    ["-m", "apa_core.cli", "serve",
     "--port", String(port),
     "--journals", path.join(APA_DIR, "data", "*.jsonl"),
     "--processes-dir", path.join(APA_DIR, "data", "processes"),
     "--frontend-dist", path.join(__dirname, "..", "dist")],
    { cwd: APA_DIR, stdio: ["ignore", logFd, logFd] });

  await waitHealthy(port);
  console.log(`[desktop] serve ready on :${port}`);
}

async function main() {
  // 启动前置检查：依赖必须已通过 pnpm setup 安装（不在运行时装载）
  try {
    execSync(`"${VENV_PY}" -c "import apa_core"`, { timeout: 10_000 });
  } catch {
    console.error(
      "[desktop] Python dependencies not installed.\n" +
      "         Run first: cd apa/frontend && pnpm setup");
    app.quit();
    return;
  }

  const port = await freePort();
  await startServe(port);

  mainWindow = new BrowserWindow({
    width: 1280, height: 800, minWidth: 900,
    title: "APA Desktop",
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}`);
}

app.whenReady().then(main);
app.on("window-all-closed", () => {
  if (pythonProc) pythonProc.kill("SIGTERM");
  app.quit();
});