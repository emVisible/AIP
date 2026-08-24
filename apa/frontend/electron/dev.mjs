/**
 * 开发编排器：一条命令启动全栈。
 *
 *   pnpm dev = Python serve + electron-vite dev (vite HMR + Electron)
 *
 * Python serve 先启动（提供 /api），然后 electron-vite 启动渲染器
 * （/api proxy 转发到 Python 端口）+ Electron 主进程。
 */
import { spawn } from "child_process";
import path from "path";
import net from "net";

const FRONTEND = path.resolve(import.meta.dirname, "..");
const APA_DIR = path.resolve(FRONTEND, "..");
const VENV_PY = path.join(APA_DIR, ".venv", "bin", "python");

const children = [];

function killAll() {
  for (const c of children) {
    try { c.kill("SIGTERM"); } catch { /* already dead */ }
  }
}

process.on("SIGINT", () => { killAll(); process.exit(0); });
process.on("SIGTERM", () => { killAll(); process.exit(0); });

function freePort() {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

async function main() {
  // ① 检查 venv
  try {
    const { execSync } = await import("child_process");
    execSync(`"${VENV_PY}" -c "import apa_core"`, { timeout: 10_000 });
  } catch {
    console.error("[dev] python deps missing — run: pnpm setup");
    process.exit(1);
  }

  // ② 启动 Python serve
  const port = 8686;   // 与 electron.vite.config.ts proxy target 一致
  console.log(`[dev] starting serve on :${port} ...`);
  const py = spawn(VENV_PY, [
    "-m", "apa_core.cli", "serve",
    "--port", String(port),
    "--journals", path.join(APA_DIR, "data", "*.jsonl"),
    "--processes-dir", path.join(APA_DIR, "data", "processes"),
  ], {
    cwd: APA_DIR,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env },
  });
  children.push(py);
  py.stdout.on("data", (d) => process.stdout.write(`[serve] ${d}`));
  py.stderr.on("data", (d) => process.stderr.write(`[serve:err] ${d}`));

  // 等 serve 就绪
  const deadline = Date.now() + 15_000;
  let healthy = false;
  while (Date.now() < deadline && !healthy) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/processes`);
      if (r.ok) { healthy = true; break; }
    } catch { /* not yet */ }
    await new Promise(r => setTimeout(r, 300));
  }
  if (!healthy) {
    console.error("[dev] serve failed to start");
    killAll();
    process.exit(1);
  }
  console.log(`[dev] serve ready on :${port}`);

  // ③ electron-vite dev（注入 serve 端口供 proxy 使用）
  console.log("[dev] starting electron-vite ...");
  const ev = spawn("npx", ["electron-vite", "dev"], {
    cwd: FRONTEND,
    stdio: "inherit",
    env: {
      ...process.env,
      APA_SERVE_PORT: String(port),
    },
  });
  children.push(ev);

  ev.on("exit", (code) => {
    killAll();
    process.exit(code ?? 0);
  });
}

main().catch(e => {
  console.error("[dev] fatal:", e);
  killAll();
  process.exit(1);
});