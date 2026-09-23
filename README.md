# Clearance（放行）· 中文后台审核网关

> `内容提交 → 引擎快判 → 自动过 / 自动拦 / 转人工`。
> A review gateway for Chinese ops backoffices: submit → decide → auto-approve /
> auto-reject / human. Auto-decisions carry confidence + audit; wrong auto-pass
> is treated as more expensive than human review.

## 为什么存在 Why

| 难题 Pain | 做法 Approach |
|---|---|
| **不敢自动批**：过自信、无校准的模型没人敢放行。Overconfident, uncalibrated models can't be trusted with auto-approve. | 校准置信 + 置信门控 + 全审计；自动放错零容忍（`auto_err` 必须为 0）。Calibrated confidence + gating + audit. |
| **审不起**：按 token 计费、秒级延迟；传统分类器每垂类重标数据。Costly, slow review; classifiers need relabeling per domain. | 自托管 Laya（$0，单次前向）；日常人工决议沉淀为标签，500+ 条后开微调。Self-hosted $0 inference; daily resolutions become labels. |
| **领域漂移**：新话术一出模型就过时。Models go stale on new slang and scams. | 飞轮链路已通：`resolve → 沉淀 → 重拟合/微调 → A/B 回归`。Refit loop implemented; effect pending real data. |

## 原则 Principles

1. **语义事件**：只传业务语义，不传遥测与大对象；超 4KB 拒绝，大对象走引用（`body_ref` + `context.get`）。
2. **最小充分上下文**：每次决策只拿判题所需的字段。
3. **AI 无执行权**：引擎输出必须经过注册表校验与门控才能生效，不可绕过。
4. **门控**：置信度过线才自动执行，否则转人工。无可用模型引擎时 heuristic 照判（fail-open，离线优先的故意选择）。
5. **一切可审计**：只追加审计流；终态单向（pending → approved/rejected），不可回迁。

1. **Semantic events**: business semantics only; >4KB rejected, large objects by reference.
2. **Minimum sufficient context** per decision.
3. **AI holds no execution power**: engine output must pass registry validation + gating.
4. **Confidence gating**: auto-execute only above threshold, else human. No model engine → heuristic fallback (fail-open by design, offline-first).
5. **Everything auditable**: append-only audit; terminal states never transition back.

## 运行 Quickstart

```bash
./start.sh                 # sidecar :8685 + 后端 :8686 + 前端 :5173，Ctrl-C 全停
NO_SIDECAR=1 ./start.sh    # 跳过 sidecar，纯 heuristic 秒起
```

要求：`python3` + `node` + `pnpm`（后端优先 `uv run --no-sync`，
无 uv 自动回落系统 python；主产品 stdlib 零依赖，不联网也能起）。

```bash
python3 -m unittest discover -s tests -v   # 自检 tests
python3 -m core.cli demo                    # 3 条样例走完全链路
```

前端：`cd web && pnpm install && pnpm dev`（:5173，`/api` 代理到 :8686）。

## 引擎 Engines（真插槽，可替换 swappable）

| 引擎 Engine | 性质 | 缺席时 |
|---|---|---|
| `rules` | 确定性规则，零模型 deterministic rules, no model | 永不缺席 |
| `laya:sidecar` | 自托管 Laya（$0），`vendor/laya_sidecar` 独立进程，默认 `multilingual` | 自动跳过 skipped |
| `jev` | TypeSafe 云端 API（需 `TYPESAFE_API_KEY`） | 自动跳过 skipped |
| `heuristic` | 关键词兜底 keyword fallback | 永远在线 |

顺序 env `ENGINE_ORDER` 可覆（默认成本优先 cost-first）。
横评 compare：`python3 -m eval.sweep samples.jsonl --engine {rules,laya:sidecar,jev,heuristic}`。

## 校准与沉淀 Calibration & labels

```bash
python3 -m eval.sweep eval/samples_example.jsonl  # 合成样本验链路（不送拟合）
python3 -m eval.export --out eval/samples.jsonl   # 从审计+人工决议沉淀标签
python3 -m eval.calibrate --samples eval/samples.jsonl --out eval/calibration.json
```

- 温度拟合几十条即有效；微调需 500+ 条（届时开 notebook，`MODEL_DIR` 切换 checkpoint，sweep A/B 回归）。
- `expected==review` 的行自动跳过（弃权类不可标定）；合成样本只验链路，不提交拟合表。

## API 与配置 API & config

| 端点 Endpoint | 用途 |
|---|---|
| `POST /api/review/submit` | 提交 `{kind,title,body,meta?}`（大正文自动引用化） |
| `POST /api/review/<id>/resolve` | 人审 `{outcome, actor}` |
| `POST /api/context/get` | 按字段取引用对象，禁 `["*"]` |
| `GET /api/queue?state=` · `GET /api/stats` · `GET /api/health` | 队列 / 统计 / 引擎状态 |
| `GET /api/events` | SSE 实时流（hello + accepted/running/terminal/submitted/resolved/stats） |

| 环境变量 Env | 默认 Default | 含义 |
|---|---|---|
| `ENGINE_ORDER` | rules,laya:sidecar,jev,heuristic | 级联顺序 |
| `LAYA_SIDECAR_URL` / `LAYA_SIDECAR_TIMEOUT` | 127.0.0.1:8685 / 15s | sidecar 地址与超时（冷启动首推慢，宁宽） |
| `TYPESAFE_API_KEY` / `JEV_MODEL` | 空 / jev-latest | Jev 云端 key 与模型 |
| `LAYA_DEFAULT` / `LAYA_PRELOAD` / `LAYA_HEAD_MAX_LEN` | multilingual / 英+多 / 空 | 路由默认 / 预热列表 / 选项预算 |
| `MODEL_DIR` / `CALIBRATION_FILE` | Hub 官方 / eval/calibration.json | 微调 checkpoint / 温度表（热重载） |
| `COD_BLOB_THRESHOLD` | 2048 字符 | 正文引用化阈值 |
| `PORT` / `CLEARANCE_DATA_DIR` | 8686 / data/ | 后端端口 / 数据目录 |

## 布局 Layout（根即产品）

```
├── core/               引擎插槽 + 网关 + 存储 + 服务
├── vendor/
├── vendor/
│   ├── laya_sidecar/   Laya 独立决策服务（torch 隔离，代码跟踪）
│   └── laya/           上游 checkout（只读，忽略）
│   └── laya/           上游 checkout（只读，忽略）
├── eval/               sweep + 拟合 + 沉淀 + 样本
├── web/                前端（pnpm + Vite + React + TS）
├── tests/              unittest（stdlib）   ·   data/ 运行时产物
└── start.sh            一键三进程
```

动作注册表（7 个，幂等/risk 只在 `gateway.py:REGISTRY` 声明）：
`context.get`(L0)、`review.defer`(L1)、`human.task.create`(L1)、
`review.approve`(L2)、`review.reject`(L2)、`notify.send`(L2)、
`session.complete`(L0)。L3/L4 不存在——出现即转人工（故意缺席 by design）。

## 非目标 Non-goals

录制 / 桌面自动化 / 浏览器抓取 / 低代码画布 / Electron / VLM 截图进协议。

## 路线图 Roadmap

- [ ] 500+ 真实标签 → 首轮微调 + A/B 回归（`MODEL_DIR`）
- [ ] `cancelled` 态（人审超时/撤回，pending 不烂尾）
- [ ] 驳回结构化理由字段（可回流训练）
- [ ] 阈值预设（一键严格/均衡/宽松）
- [ ] submit 全异步（202 + 轮询；当前同步 + SSE 进度事件已够用，暂缓）

## License / 历史 History

MIT（见 `LICENSE`）。旧 RPA 重资产封存于 `archive/apa-rpa` 分支；行为以代码和测试为准。
