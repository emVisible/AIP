/**
 * 打包暂存：PyInstaller 冻结 APA 服务 → Resources/apa-server。
 *
 * 用法：pnpm dist:prep
 * 产物：frontend/desktop-resources/frozen/apa_server/
 *   apa_server           主可执行文件
 *   _internal/           Python 运行时 + registries/ + templates/（spec datas）
 *
 * 冻结态自包含（注册表与模板在 _MEIPASS 内解析），跨机器可分发；
 * 可写数据由 Electron main.cjs 指到 userData。
 */
const { execSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const FRONTEND = path.resolve(__dirname, "..");
const APA_DIR = path.resolve(FRONTEND, "..");
const OUT = path.join(FRONTEND, "desktop-resources", "frozen");
const WORK = process.env.APA_PYBUILD || path.join(os.tmpdir(), "apa_pybuild");

function main() {
  const t0 = Date.now();

  // ① 确认前端已构建（Electron 加载 dist/）
  if (!fs.existsSync(path.join(FRONTEND, "dist", "index.html"))) {
    console.error("[stage] frontend/dist missing — run `pnpm build` first");
    process.exit(1);
  }

  // ② PyInstaller 冻结
  fs.rmSync(OUT, { recursive: true, force: true });
  console.log("[stage] pyinstaller freezing ...");
  execSync(
    `${path.join(APA_DIR, ".venv", "bin", "python")} -m PyInstaller ` +
    `--noconfirm --clean --distpath "${OUT}" --workpath "${WORK}" ` +
    `"${path.join(FRONTEND, "apa_server.spec")}"`,
    { stdio: "inherit" });

  const bin = path.join(OUT, "apa_server", "apa_server");
  if (!fs.existsSync(bin)) {
    console.error("[stage] frozen binary missing:", bin);
    process.exit(1);
  }

  // ③ 冒烟：冻结进程能起 HTTP 并响应
  console.log("[stage] smoke test ...");
  const { spawn } = require("child_process");
  const port = 18999;
  const proc = spawn(bin,
    ["serve", "--port", String(port),
     "--journals", "/tmp/*.jsonl",
     "--processes-dir", path.join(os.tmpdir(), "apa_stage_pd")],
    { stdio: "ignore" });
  const deadline = Date.now() + 20_000;
  (function poll() {
    fetch(`http://127.0.0.1:${port}/api/processes`)
      .then(r => {
        proc.kill("SIGTERM");
        if (!r.ok) throw new Error(String(r.status));
        const mb = Math.round(execSync(
          `du -sm "${path.join(OUT, "apa_server")}"`)
          .toString().split("\t")[0]);
        console.log(`[stage] done in ${((Date.now() - t0) / 1000).toFixed(1)}s` +
          ` — frozen runtime ${mb} MB ✓`);
      })
      .catch(() => {
        if (Date.now() > deadline) {
          proc.kill("SIGKILL");
          console.error("[stage] smoke test FAILED — frozen server not healthy");
          process.exit(1);
        }
        setTimeout(poll, 400);
      });
  })();
}

main();