#!/usr/bin/env bash
# ============================================================
# APA WebUI 一键启动
#
# 用法：
#   ./webui.sh                     # 启动 Studio（默认端口 8686）
#   ./webui.sh --demo              # 先跑一个演示会话再启动（有数据可看）
#   ./webui.sh --serve --jobs jobs.yaml   # 常驻：面板+调度器+执行
#   ./webui.sh --port 9000         # 指定端口
#   ./webui.sh --token secret      # 启用 Bearer 认证
#   ./webui.sh --tenant corp_x     # 只看某租户
#   ./webui.sh --no-browser        # 不自动打开浏览器
#
# 首次运行会自动：创建 .venv → 安装本仓库各包与依赖。
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # apa/
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PORT="8686"
TOKEN=""
TENANT=""
OPEN_BROWSER="1"
DEMO="0"
SERVE="0"
JOBS=""
DATA_DIR="$SCRIPT_DIR/data"
JOURNAL_ARGS=()   # 传给 studio 的 --journals 参数

usage() { sed -n '2,16p' "$0"; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)       PORT="$2"; shift 2 ;;
    --token)      TOKEN="$2"; shift 2 ;;
    --tenant)     TENANT="$2"; shift 2 ;;
    --no-browser) OPEN_BROWSER="0"; shift ;;
    --demo)       DEMO="1"; shift ;;
    --serve)      SERVE="1"; shift ;;
    --jobs)       JOBS="$2"; shift 2 ;;
    --journal)    JOURNAL_ARGS+=("--journals" "$2"); shift 2 ;;
    -h|--help)    usage ;;
    *) echo "未知参数: $1（--help 查看用法）"; exit 2 ;;
  esac
done

echo "==> APA WebUI"
echo "    仓库: $REPO_ROOT"

# ---------- 1. Python 虚拟环境 ----------
VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "==> 创建虚拟环境 .venv ..."
  python3 -m venv "$VENV"
fi

# ---------- 2. 依赖（幂等：能导入即跳过） ----------
if ! "$PY" - <<'EOF' >/dev/null 2>&1
import apa_core, yaml, jsonschema, httpx  # noqa
EOF
then
  echo "==> 安装依赖（仅首次，约 1 分钟）..."
  "$VENV/bin/pip" install -q -U pip
  "$VENV/bin/pip" install -q \
    -e "$REPO_ROOT/sdk/python" \
    -e "$SCRIPT_DIR/packages/apa-core" \
    -e "$SCRIPT_DIR/packages/apa-sdk-python" \
    -e "$SCRIPT_DIR/packages/apa-executors" \
    pyyaml jsonschema httpx websockets
fi

mkdir -p "$DATA_DIR" "$DATA_DIR/processes"

# ---------- 3. 可选演示数据 ----------
if [[ "$DEMO" == "1" ]]; then
  echo "==> 运行演示会话（大额发票人工批准，约 3 秒）..."
  "$PY" "$SCRIPT_DIR/examples/human-approval/run.py" --auto approve >/dev/null || true
  SRC="$SCRIPT_DIR/examples/human-approval/.session.jsonl"
  if [[ -f "$SRC" ]]; then
    cp "$SRC" "$DATA_DIR/demo_human_approval.jsonl"
  fi
fi

JOURNAL_ARGS+=(--journals "$DATA_DIR/*.jsonl")

# ---------- 4. 浏览器 ----------
open_browser() {
  sleep 1.2
  URL="http://127.0.0.1:$PORT"
  if [[ "$OPEN_BROWSER" == "1" ]]; then
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
    else echo "→ 打开 $URL"
    fi
  fi
}

CMD=(python -m apa_core.cli studio
     --journals "$DATA_DIR/*.jsonl"
     --port "$PORT")

EXTRA=()
[[ -n "$TENANT" ]] && EXTRA+=(--tenant "$TENANT")
[[ -n "$TOKEN"  ]] && EXTRA+=(--token  "$TOKEN") && echo "==> 已启用 Bearer 认证（浏览器直连需带令牌，见 README）"

echo "==> 启动: http://127.0.0.1:$PORT   （Ctrl-C 停止）"
open_browser &

cd "$SCRIPT_DIR"
if [[ "$SERVE" == "1" ]]; then
  echo "==> 常驻模式：面板 + 调度器 + 本地流程执行"
  SERVE_ARGS=(--journals "$DATA_DIR/*.jsonl" --port "$PORT"
              --processes-dir "$DATA_DIR/processes")
  [[ -n "$JOBS"   ]] && SERVE_ARGS+=(--jobs "$JOBS")
  [[ -n "$TENANT" ]] && SERVE_ARGS+=(--tenant "$TENANT")
  [[ -n "$TOKEN"  ]] && SERVE_ARGS+=(--token "$TOKEN")
  exec "$PY" -m apa_core.cli serve "${SERVE_ARGS[@]}"
fi

exec "$PY" -m apa_core.cli studio \
  --journals "$DATA_DIR/*.jsonl" \
  --port "$PORT" \
  ${TENANT:+--tenant "$TENANT"} \
  ${TOKEN:+--token "$TOKEN"}
