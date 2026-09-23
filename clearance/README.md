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
│   ├── decide.py      决策引擎：有 laya 走 Router，无则 heuristic（诚实标注）
│   ├── gateway.py     最小校验链：Registry ∈ 检查 + C4 凭据扫描 + 置信度门控 + 审计
│   ├── store.py       文件存储（reviews.json + audit.jsonl，无 DB）
│   └── cli.py         命令行：submit / resolve / queue / demo
├── tests/             unittest（stdlib，无第三方依赖）
└── data/              运行时产物（gitignored）
```

## 运行（一键启动）

```bash
./start.sh   # 前端 :5173 + 后端 :8686，Ctrl-C 全停
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

## 接 Laya（可选增强）

```bash
pip install laya
python3 -m clearance_core.cli demo   # engine 自动从 heuristic 切到 laya
```

`decide.py` 用 `Router(preload)` 常驻思想：进程内单例 Router，`max_loaded=2`
（english + multilingual），中英混流无 reload 惩罚。微调与 temperature 拟合
是下一步（先拿 50-100 条真实审核单做种子）。

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
