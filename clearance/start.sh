#!/usr/bin/env bash
# Clearance 一键启动：Laya sidecar + 后端 API + 前端 dev，Ctrl-C 一起停。
#   ./start.sh                 # 前端 :5173 · 后端 :8686 · sidecar :8685
#   PORT=9000 ./start.sh       # 换后端端口（前端代理跟随需改 web/vite.config.ts）
#   NO_SIDECAR=1 ./start.sh    # 跳过 sidecar（纯 heuristic，零下载秒起）
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8686}"
SIDECAR_PORT="${SIDECAR_PORT:-8685}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺 $1，请先安装（$2）"; exit 1; }; }
need python3 "https://www.python.org/downloads/"
need node "https://nodejs.org/"
need pnpm "corepack enable && corepack prepare pnpm@latest --activate"

if command -v uv >/dev/null 2>&1; then UV=uv; else
  echo "[start] 未检测到 uv，用系统 python3（建议安装 https://docs.astral.sh/uv/）"
  UV=""
fi
run_py() { if [ -n "$UV" ]; then $UV run --no-sync python "$@"; else python3 "$@"; fi; }
export SIDECAR_PORT

PIDS=""

# ① Laya sidecar（独立 venv，重依赖隔离；失败则主 API 自动 heuristic）
if [ "${NO_SIDECAR:-0}" != "1" ] && [ -n "$UV" ]; then
  if (cd laya_sidecar && uv sync >/dev/null 2>&1); then
    (cd laya_sidecar && exec uv run --no-sync python server.py) &
    PIDS="$PIDS $!"
    echo "[start] sidecar 启动中 :${SIDECAR_PORT}（首次需下载 checkpoint，约 1GB）"
  else
    echo "[start] sidecar 跳过（uv sync 失败）：engine=heuristic"
  fi
else
  echo "[start] sidecar 跳过：engine=heuristic"
fi

# ② 后端 API（stdlib，主产品秒起）
run_py -m clearance_core.server --port "$PORT" &
PIDS="$PIDS $!"

# ③ 前端 dev
(cd web && { [ -d node_modules ] || pnpm install; }) >/dev/null
(cd web && exec env PORT=5173 pnpm dev) &
PIDS="$PIDS $!"

cleanup() { kill $PIDS 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo ""
echo "  前端    http://127.0.0.1:5173"
echo "  后端    http://127.0.0.1:$PORT  (/api/health)"
echo "  sidecar http://127.0.0.1:$SIDECAR_PORT  (/health)"
echo "  按 Ctrl-C 全部停止"
wait
