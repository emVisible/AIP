/**
 * APA Desktop — Electron 主进程。
 *
 * 职责（§12.1 单一权威）：
 *   · Python serve sidecar 编排（spawn→健康检查→崩溃重启）
 *   · BrowserWindow 加载 React SPA
 *   · 退出时清理全部子进程
 */
const { app, BrowserWindow } = require("electron");
const { spawn, execSync } = require("child_process");
const net = require("net");
const path = require("path");
const http = require("http");

const APA_DIR = path.resolve(__dirname, "..");
const VENV_PY = path.join(APA_DIR, ".venv", "bin", "python");
const SERVE_LOG = path.join(app.getPath("userData"), "serve.log");

let pythonProc = null;
let mainWindow = null;
let restarting = false;

// ---- 端口分配 ----
function freePort() {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

// ---- Python 自举 ----
function ensurePython() {
  try {
    execSync(`"${VENV_PY}" -c "import apa_core"`, { timeout: 10_000 });
    return true;
  } catch { return false; }
}

function bootstrapPython() {
  console.log("[desktop] bootstrapping Python venv ...");
  execSync(
    `python3 -m venv "${VENV_PY}/../.." && ` +
    `"${VENV_PY}" -m pip install -q -U pip && ` +
    `"${VENV_PY}" -m pip install -q ` +
    `-e "${path.join(REPO_ROOT, "sdk/python")}" ` +
    `-e "${path.join(APA_DIR, "packages/apa-core")}" ` +
    `-e "${path.join(APA_DIR, "packages/apa-sdk-python")}" ` +
    `-e "${path.join(APA_DIR, "packages/apa-executors")}" ` +
    `pyyaml jsonschema httpx websockets`,
    { cwd: REPO_ROOT, timeout: 300_000, stdio: "inherit" },
  );
}

const REPO_ROOT = path.resolve(APA_DIR, "..");

// ---- serve sidecar ----
function startServe(port) {
  const logFd = require("fs").openSync(SERVE_LOG, "a");
  pythonProc = spawn(
    VENV_PY,
    ["-m", "apa_core.cli", "serve",
     "--port", String(port),
     "--journals", path.join(APA_DIR, "data", "*.jsonl"),
     "--processes-dir", path.join(APA_DIR, "data", "processes")],
    { cwd: REPO_ROOT, stdio: ["ignore", logFd, logFd] },
  );

  pythonProc.on("exit", (code) => {
    console.log(`[desktop] serve exited code=${code}`);
    if (!restarting && !app.isQuitting) restartServe(port);
  });

  // 健康轮询
  const deadline = Date.now() + 60_000;
  const check = async () => {
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`http://127.0.0.1:${port}/api/processes`);
        if (res.ok) return true;
      } catch {}
      await new Promise(r => setTimeout(r, 500));
    }
    return false;
  };
  return check().then(ok => {
    if (!ok) throw new Error("serve health check failed");
    console.log(`[desktop] serve healthy on port ${port}`);
  });
}

function restartServe(port) {
  if (restarting) return;
  restarting = true;
  setTimeout(() => {
    restarting = false;
    startServe(port).catch(() => {});
  }, 3_000);
}

// ---- 健康检查 helper ----
function waitHealthy(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const poll = () => {
      if (Date.now() > deadline) {
        reject(new Error("health check timeout"));
        return;
      }
      fetch(`http://127.0.0.1:${port}/api/processes`)
        .then(r => (r.ok ? resolve() : setTimeout(poll, 500)))
        .catch(() => setTimeout(poll, 500));
    };
    poll();
  });
}

// ---- 主流程 ----
async function main() {
  // 1. Python 自举
  if (!ensurePython()) bootstrapPython();

  // 2. 分配端口并启动
  const port = await freePort();
  await startServe(port);
  await waitHealthy(port, 30_000);

  // 3. 创建窗口
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    title: "APA Desktop",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}`);

  mainWindow.on("closed", () => { mainWindow = null; });
}

app.whenReady().then(main);

app.on("window-all-closed", () => {
  if (pythonProc) pythonProc.kill("SIGTERM");
  app.isQuitting = true;
  app.quit();
});