# Clearance（放行）— AIP 的产品实现

> 通用后台审核网关：`review.submit → Laya 快判 → 自动过 / 自动拦 / 转人工`。
> AIP 只做可靠运行时，Laya 只做 typed 决策（`choice/score/noul`）。

## 非目标（写死，不做）

录制 / 桌面自动化 / 浏览器抓取 / 低代码画布 / Electron / VLM 截图进协议。

旧 RPA 重资产不在此目录：只活在 `archive/apa-rpa` 分支 + tag，工作区不留文件。
本目录只依赖 AIP Kernel 思想，不依赖任何旧代码。

## 布局

```
clearance/
├── clearance_core/
│   ├── models.py      数据模型（ReviewItem / Decision / ReviewRecord）
│   ├── questions.py   通用 6 问（Laya choice/score/noul 格式，可配 category）
│   ├── decide.py      SidecarClient：调 laya_sidecar，缺席降级 heuristic（诚实标注）
│   ├── gateway.py     最小校验链：Registry ∈ 检查 + C4 凭据扫描 + 置信度门控 + 审计
│   ├── store.py       文件存储（reviews.json + audit.jsonl，无 DB）
│   ├── server.py      HTTP API（stdlib，/api/health|queue|stats|review/*）
│   └── cli.py         命令行：submit / resolve / queue / demo
├── laya_sidecar/      Laya 独立决策服务（torch 依赖隔离，详见其 README）
├── eval/              阈值 sweep + 样本格式
├── web/               前端（pnpm + Vite + React + TS）
├── PROTOCOL.md        AIP→实现一页对照表（唯一概念文档）
├── CHANGELOG.md
├── start.sh           一键三进程
└── data/              运行时产物（gitignored）
```

## 运行（一键启动）

```bash
./start.sh                 # sidecar :8685 + 后端 :8686 + 前端 :5173，Ctrl-C 全停
NO_SIDECAR=1 ./start.sh    # 跳过 sidecar，纯 heuristic 秒起
```

要求：`python3` + `node` + `pnpm`（后端优先走 `uv run --no-sync`，
无 uv 自动回落系统 python；后端 stdlib 零依赖，不联网也能起）。

## 手动运行

```bash
cd clearance
python3 -m unittest discover -s tests -v   # 自检
python3 -m clearance_core.cli demo          # 3 条样例走完全链路
python3 -m clearance_core.cli submit --kind article --title "示例" --body "正文..."
python3 -m clearance_core.cli queue --state pending
python3 -m clearance_core.cli resolve --id <id> --outcome approve --actor admin
```

后端 HTTP（给前端用，同样 stdlib）：

```bash
python3 -m clearance_core.server --port 8686   # /api/health|queue|stats|review/submit|review/<id>/resolve
```

前端（`web/`，pnpm + Vite + React + TS）：

```bash
cd web && pnpm install && pnpm dev    # :5173，/api 代理到 :8686
pnpm build                            # tsc + vite 生产构建
```

## 调优（eval）

```bash
python3 -m eval.sweep eval/samples_example.jsonl  # 自带合成样本，验证链路
python3 -m eval.sweep /path/to/your_samples.jsonl # 真实样本定阈值
```

样本格式与脱敏要求见 `eval/README.md`。原则：自动放错比转人工贵，
宁可 human_rate 高，不可 auto_err > 0。

## 接 Laya（sidecar，默认开启）

```bash
cd laya_sidecar && uv sync   # 首次：装 laya + torch（约 2GB，需联网）
python3 -m clearance_core.cli demo   # sidecar 可达时 engine 自动切 laya:sidecar
```

主产品永远 stdlib：sidecar 缺席时诚实降级 heuristic，`/api/stats` 如实标注。
`MODEL_DIR` 可切换微调后 checkpoint；`category>20` 项自动 shortlist。详见
`laya_sidecar/README.md`。

## 动作注册表（当前 7 个，C3：幂等/risk 只在此声明）

| action | risk | 含义 |
|---|---|---|
| `context.get` | L0 | 按需取原文（CoD） |
| `review.defer` | L1 | 延迟复审 |
| `human.task.create` | L1 | 转人工（Session 挂起） |
| `review.approve` | L2 | 自动通过（conf≥0.85 才放行） |
| `review.reject` | L2 | 自动驳回（conf≥0.85 才放行） |
| `notify.send` | L2 | 通知提交人 |
| `session.complete` | L0 | 归档 |

L3/L4（支付/签约等不可逆动作）本网关不存在——出现即转人工，这是故意缺席。
