/**
 * 一次性安装 Python venv + 依赖（与 pnpm start 分离）。
 * 运行时机：首次使用或依赖变更后手动执行。
 */
const { execSync } = require("child_process");
const path = require("path");

const APA_DIR = path.resolve(__dirname, "..", "..");
const REPO_ROOT = path.resolve(APA_DIR, "..");
const VENV_PY = path.join(APA_DIR, ".venv", "bin", "python");

function main() {
  // 幂等检查
  try {
    execSync(`"${VENV_PY}" -c "import apa_core"`, { timeout: 10_000 });
    console.log("[setup] dependencies already installed ✓");
    return;
  } catch {
    // 未安装 → 继续
  }

  console.log("[setup] creating venv and installing packages ...");

  const pythonBin = process.platform === "win32" ? "python" : "python3";
  const cmds = [
    `${pythonBin} -m venv "${path.join(APA_DIR, ".venv")}"`,
    `"${VENV_PY}" -m pip install -q -U pip`,
    `"${VENV_PY}" -m pip install -q ` +
      `-e "${path.join(REPO_ROOT, "sdk/python")}" ` +
      `-e "${path.join(APA_DIR, "packages/apa-core")}" ` +
      `-e "${path.join(APA_DIR, "packages/apa-sdk-python")}" ` +
      `-e "${path.join(APA_DIR, "packages/apa-executors")}" ` +
      `pyyaml jsonschema httpx websockets`,
  ];

  for (const cmd of cmds) {
    execSync(cmd, { cwd: REPO_ROOT, timeout: 300_000, stdio: "inherit" });
  }
  console.log("[setup] done ✓ — run 'pnpm start' to launch");
}

main();