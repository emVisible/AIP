/**
 * APA Desktop — Electron 主进程。
 * 职责：Python serve sidecar 编排 + BrowserWindow 加载 React SPA。
 *
 * 两种模式：
 *   开发态（app.isPackaged=false）：APA_DIR = 仓库 apa/ 目录，
 *     直接用 .venv 与仓库 registries/templates/data。
 *   打包态：apa-runtime 由 stage-desktop.cjs 暂存到 Resources，
 *     可写数据放 userData（journals/processes/logs）。
 */
const { app, BrowserWindow } = require("electron");
const { spawn, execSync } = require("child_process");
const { mkdtempSync } = require("fs");
const fs = require("fs");
const os = require("os");
const path = require("path");

const isDev = !app.isPackaged;

// ---- 路径解析 ---------------------------------------------------------------
function resolveLayout() {
  if (isDev) {
    const apaDir = path.resolve(__dirname, "..", "..");
    return {
      apaDir,
      venvPy: path.join(apaDir, ".venv", "bin", "python"),
      registriesDir: null,          // serve 用默认 default_registries()
      processesDir: path.join(apaDir, "data", "processes"),
      journalGlob: path.join(apaDir, "data", "*.jsonl"),
      logFile: path.join(apaDir, "serve.log"),
      cwd: apaDir,
    };
  }
  // 打包态：Resources/apa-server（stage-desktop.cjs 的 PyInstaller 冻结产物）
  const rt = path.join(process.resourcesPath, "apa-server");
  const userData = app.getPath("userData");   // ~/Library/Application Support/APA Desktop
  fs.mkdirSync(path.join(userData, "processes"), { recursive: true });
  fs.mkdirSync(path.join(userData, "journals"), { recursive: true });
  return {
    apaDir: rt,
    serverBin: rt,                // 冻结可执行文件 <...>/apa-server/apa_server
    registriesDir: null,          // 注册表/模板已打进 _internal，冻结态自动解析
    processesDir: path.join(userData, "processes"),
    journalGlob: path.join(userData, "journals", "*.jsonl"),
    logFile: path.join(userData, "serve.log"),
    cwd: userData,
  };
}

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

async function startServe(port, L) {
  const isFrozen = !!L.serverBin;
  const bin = isFrozen ? path.join(L.serverBin, "apa_server") : L.venvPy;
  const args = isFrozen
    ? ["serve", "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir]
    : ["-m", "apa_core.cli", "serve",
       "--port", String(port),
       "--journals", L.journalGlob,
       "--processes-dir", L.processesDir,
       "--frontend-dist", path.join(__dirname, "..", "dist")];

  const logFd = fs.openSync(L.logFile, "a");
  pythonProc = spawn(bin, args,
    { cwd: L.cwd, stdio: ["ignore", logFd, logFd] });

  await waitHealthy(port);
  console.log(`[desktop] serve ready on :${port}`);
}

async function main() {
  const L = resolveLayout();

  // 启动前置检查：冻结二进制存在 / 开发态依赖已装
  const checkBin = isDev
    ? L.venvPy
    : path.join(L.serverBin, "apa_server");
  try {
    if (isDev) {
      execSync(`"${checkBin}" -c "import apa_core"`, { timeout: 10_000 });
    } else {
      fs.accessSync(checkBin, fs.constants.X_OK);
    }
  } catch {
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