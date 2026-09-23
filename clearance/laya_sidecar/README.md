# laya_sidecar — Laya 独立决策服务

把 torch 系重依赖（约 2GB）隔离在独立进程 + 独立 venv，
Clearance 主产品保持 stdlib、秒启动、不联网可跑。

## 启动

```bash
cd clearance/laya_sidecar
uv sync                       # 首次：建 venv 并装 laya（含 torch，约 2GB，需联网）
uv run --no-sync python server.py
```

`./start.sh` 会自动做这件事；`uv sync` 失败时 warn 后跳过，
主 API 照常以 heuristic 启动。

## 环境变量

| 变量 | 默认 | 含义 |
|---|---|---|
| `SIDECAR_PORT` | 8685 | 监听端口 |
| `LAYA_DEFAULT` | multilingual | 路由默认 checkpoint（中文优先；英文自动切 english） |
| `LAYA_LAZY=1` | 启动即 preload | 跳过预热，首次 `/decide` 时加载 |
| `LAYA_MAX_LOADED` | 2 | 常驻 checkpoint 数（english + multilingual） |
| `LAYA_PRELOAD` | english,multilingual | 启动预热列表（中文单语部署可只写 `multilingual`，省一半下载/内存） |
| `LAYA_HEAD_MAX_LEN` | 不覆盖 | 覆盖选项 token 预算（高基数时调大；超 20 项已自动 shortlist） |
| `SHORTLIST_K` | 20 | shortlist 保留数（官方 `predict_shortlist` API） |
| `MODEL_DIR` | Hub 官方包 | 覆盖 checkpoint：本地微调产物目录或 Hub repo |

`/decide` 支持 `lang_guess`（语言代码或留空走内置检测），短文本可显式指定。
`choice` 选项超 20 时自动走官方 shortlist；校准温度拟合完成前，
主产品 reasons 会标注 `uncalibrated`（见官方校准说明）。

## 行为

- 启动 preload english + multilingual（Mac 自动 MPS，失败回 CPU 并明示）。
- 任一 `choice` 选项超 20 时自动 `predict_shortlist(k=20)`（laya 高基数约束）。
- `/health` 如实报告 `loaded/device`；主产品 `/api/stats` 的 engine 字段
  在 sidecar 可达时显示 `laya:sidecar`，否则 `heuristic`。
