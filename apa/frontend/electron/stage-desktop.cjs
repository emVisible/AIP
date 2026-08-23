/**
 * 打包暂存：组装 Resources/apa-runtime（Python venv + 包源码 + 资源）。
 *
 * 用法：pnpm dist:prep
 * 产物：frontend/desktop-resources/apa-runtime/
 *   .venv/           Python 运行时（含 apa-core/executors/sdk 可编辑安装）
 *   packages/        apa-core / apa-executors / apa-sdk-python 源码
 *   registries/*.yaml
 *   templates/*.yaml
 *
 * 说明：venv 按同机同架构分发设计（pyvenv.cfg home 指向本机解释器）。
 *       跨机分发需 PyInstaller 冻结，属后续里程碑。
 */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const APA_DIR = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(APA_DIR, "..");
const OUT = path.join(__dirname, "..", "desktop-resources", "apa-runtime");

function cp(src, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  execSync(`ditto "${src}" "${dest}"`, { stdio: "inherit" });
}

function main() {
  const t0 = Date.now();
  fs.rmSync(OUT, { recursive: true, force: true });

  // venv（排除缓存与符号链接目标无关项）
  console.log("[stage] copying .venv ...");
  cp(path.join(APA_DIR, ".venv"), path.join(OUT, ".venv"));

  // 重写 pyvenv.cfg 为相对提示（同机分发足够）
  // 包源码（.pth 可编辑安装指向这些路径，必须随行）
  for (const pkg of ["apa-core", "apa-executors", "apa-sdk-python"]) {
    console.log(`[stage] packages/${pkg}`);
    cp(path.join(APA_DIR, "packages", pkg),
       path.join(OUT, "packages", pkg));
  }

  // registries / templates / sdk
  console.log("[stage] registries & templates & sdk");
  cp(path.join(APA_DIR, "registries"), path.join(OUT, "registries"));
  cp(path.join(APA_DIR, "templates"), path.join(OUT, "templates"));
  cp(path.join(REPO_ROOT, "sdk"), path.join(OUT, "sdk"));

  const sizeMb = Math.round(
    execSync(`du -sm "${OUT}"`).toString().split("\t")[0]);
  console.log(`[stage] done in ${((Date.now() - t0) / 1000).toFixed(1)}s — ` +
    `${OUT} (${sizeMb} MB)`);
}

main();