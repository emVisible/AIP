#!/usr/bin/env bash
# Clearance 一键启动：后端 API + 前端 dev，Ctrl-C 一起停。
#   ./start.sh                 # 前端 http://127.0.0.1:5173，后端 http://127.0.0.1:8686
#   PORT=9000 ./start.sh       # 换后端端口（前端代理自动跟随需改 web/vite.config.ts）
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8686}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺 $1，请先安装（$2）"; exit 1; }; }
need python3 "https://www.python.org/downloads/"
need node "https://nodejs.org/"
need pnpm "corepack enable && corepack prepare pnpm@latest --activate"

# 后端：优先 uv（无依赖故 --no-sync，不联网），无 uv 回落 python3
if command -v uv >/dev/null 2>&1; then
  PY="uv run --no-sync python"
else
  echo "[start] 未检测到 uv，用系统 python3（建议安装 https://docs.astral.sh/uv/）"
  PY="python3"
fi

$PY -m clearance_core.server --port "$PORT" &
BACKEND=$!

cd web
[ -d node_modules ] || pnpm install
PORT=5173 pnpm dev &
FRONTEND=$!

cd ..
cleanup() { kill "$BACKEND" "$FRONTEND" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo ""
echo "  前端  http://127.0.0.1:5173"
echo "  后端  http://127.0.0.1:$PORT  (/api/health)"
echo "  按 Ctrl-C 全部停止"
wait
