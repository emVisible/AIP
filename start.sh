#!/usr/bin/env bash
# Clearance 一键启动：Laya sidecar + 后端 API + 前端 dev，Ctrl-C 一起停。
#   ./start.sh                 # 前端 :5173 · 后端 :8686 · sidecar :8685
#   PORT=9000 ./start.sh       # 换后端端口（前端代理跟随需改 web/vite.config.ts）
#   NO_SIDECAR=1 ./start.sh    # 跳过 sidecar（纯 heuristic，零下载秒起）
#   ./start.sh --force         # 先杀掉占用三端口的旧进程再起（会杀进程，显式opt-in）
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8686}"
SIDECAR_PORT="${SIDECAR_PORT:-8685}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺 $1，请先安装（$2）"; exit 1; }; }
need python3 "https://www.python.org/downloads/"
need node "https://nodejs.org/"
need pnpm "corepack enable && corepack prepare pnpm@latest --activate"

port_pid() { lsof -ti:"$1" 2>/dev/null | head -n 1 || true; }

# 端口预检：被占则 fail fast（不再出现“前端起来了后端是死的”）
for spec in "$SIDECAR_PORT:sidecar" "$PORT:backend" "5173:frontend"; do
  p="${spec%%:*}"
  name="${spec##*:}"
  [ "$name" = "sidecar" ] && [ "${NO_SIDECAR:-0}" = "1" ] && continue
  pid="$(port_pid "$p")"
  if [ -n "$pid" ]; then
    if [ "$FORCE" = "1" ]; then
      echo "[start] --force：杀掉 :$p 上的旧进程（pid ${pid}）"
      kill "$pid" 2>/dev/null || true
      sleep 1
    else
      cmd="$(ps -p "$pid" -o command= 2>/dev/null | head -c 100)"
      echo "[start] 端口 :$p 被占用（$name 起不来）：pid $pid $cmd"
      echo "[start] 处理：lsof -ti:$p | xargs kill ；或 ./start.sh --force（一并重起）"
      exit 1
    fi
  fi
done

if command -v uv >/dev/null 2>&1; then UV=uv; else
  echo "[start] 未检测到 uv，用系统 python3（建议安装 https://docs.astral.sh/uv/）"
  UV=""
fi
run_py() { if [ -n "$UV" ]; then $UV run --no-sync python "$@"; else python3 "$@"; fi; }
export SIDECAR_PORT

PIDS=""
die() {
  echo "[start] 启动失败：$1"
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  exit 1
}

# ① Laya sidecar（独立 venv，重依赖隔离；失败则主 API 自动 heuristic）
if [ "${NO_SIDECAR:-0}" != "1" ] && [ -n "$UV" ]; then
  if (cd vendor/laya_sidecar && uv sync >/dev/null 2>&1); then
    (cd vendor/laya_sidecar && exec uv run --no-sync python server.py) &
    PIDS="$PIDS $!"
    echo "[start] sidecar 启动中 :${SIDECAR_PORT}（首次需下载 checkpoint，约 1GB）"
  else
    echo "[start] sidecar 跳过（uv sync 失败）：engine=heuristic"
  fi
else
  echo "[start] sidecar 跳过：engine=heuristic"
fi

# ② 后端 API（stdlib，主产品秒起；起不来直接 abort，不留半吊子）
run_py -m core.server --port "$PORT" &
PIDS="$PIDS $!"
ready=0
for _ in $(seq 1 30); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = "1" ] || die "后端 :$PORT 30s 内未就绪（看上方报错；端口占用见预检）"

# ③ 前端 dev
(cd web && { [ -d node_modules ] || pnpm install; }) >/dev/null
(cd web && exec env PORT=5173 pnpm dev) &
PIDS="$PIDS $!"

cleanup() {
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "  前端    http://127.0.0.1:5173"
echo "  后端    http://127.0.0.1:$PORT  (/api/health)"
echo "  sidecar http://127.0.0.1:$SIDECAR_PORT  (/health)"
echo "  按 Ctrl-C 全部停止"
wait
