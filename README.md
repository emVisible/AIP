# Clearance（放行）· Calibrated Review Gateway for Chinese Ops Backoffices

> 中文后台内容审核（文章 / 评论 / 工单）的可信自动网关：
> `内容提交 → 引擎快判 → 自动过 / 自动拦 / 转人工`。
> A Chinese-first, calibrated auto-review gateway: submit → decide → auto-approve /
> auto-reject / human. Every auto-decision carries calibrated confidence + audit.

## 为什么存在 Why

| 业界老难题 Long-standing pain | 我们的解法 Our answer |
|---|---|
| **不敢自动批**：LLM 过自信、无校准，错放行的代价无人敢担。No one trusts auto-approve: LLMs are overconfident and uncalibrated. | RLCD 校准置信 + 持出温度拟合 + 置信门控 + 全审计。自动放错比转人工贵，所以 `auto_err` 必须为 0。Calibrated confidence (RLCD + temperature fit) + gating + full audit. |
| **审不起**：LLM 按 token 计费、秒级延迟；传统分类器每垂类重标数据、快速过期。Review at scale is costly and slow; classic classifiers need relabeling per domain. | Laya 自托管 $0、单次前向 33ms（MPS 约 300–500ms）；日常人工决议即免费标签，微调闭环越用越准。Self-hosted $0, single forward pass; daily human resolutions become free labels for fine-tuning. |
| **领域漂移**：新话术、新骗术一出模型就过时。Models go stale on new scams and slang. | 飞轮：`resolve → 样本沉淀 → 温度重拟合/微调 → A/B 回归`，网关内一键完成。Flywheel: resolutions → samples → refit/fine-tune → A/B regression, inside the gateway. |

## 原则 Principles（AIP 思想的产品表达，无单独协议文档）

1. **语义事件**：只传业务语义（kind/title/body 摘要），不传遥测与原文大对象；超 4KB 拒绝，大对象走引用。
2. **最小充分上下文**：每次决策只拿判题所需的字段，而非越全越好。
3. **AI 无执行权**：引擎输出必须经过注册表校验与门控才能生效，不可绕过。
4. **门控**：置信度过线才自动执行，否则转人工；自动放错零容忍。
5. **一切可审计**：只追加审计流；终态单向（pending → approved/rejected），不可回迁。

1. **Semantic events**: business semantics only, no telemetry; >4KB rejected, large objects by reference.
2. **Minimum sufficient context** per decision, not maximum data.
3. **AI holds no execution power**: engine output must pass registry validation + gating.
4. **Confidence gating**: auto-execute only above threshold, else human; zero tolerance for wrong auto-pass.
5. **Everything auditable**: append-only audit; terminal states never transition back.

## 运行 Quickstart

```bash
./start.sh                 # sidecar :8685 + 后端 :8686 + 前端 :5173，Ctrl-C 全停
NO_SIDECAR=1 ./start.sh    # 跳过 sidecar，纯 heuristic 秒起
```

要求：`python3` + `node` + `pnpm`（后端优先 `uv run --no-sync`，无 uv 回落系统 python；
主产品 stdlib 零依赖，不联网也能起）。

```bash
python3 -m unittest discover -s tests -v   # 自检 tests
python3 -m clearance_core.cli demo          # 3 条样例走完全链路
```

前端：`cd web && pnpm install && pnpm dev`（:5173，`/api` 代理到 :8686）。

## 引擎 Engines（真插槽，可替换 swappable）

| 引擎 Engine | 性质 | 缺席时 |
|---|---|---|
| `rules` | 确定性规则，零模型 deterministic rules, no model | 永不缺席 |
| `laya:sidecar` | 自托管 Laya（$0），独立进程，默认 `multilingual` | 自动跳过 skipped |
| `jev` | TypeSafe 云端 API（需 `TYPESAFE_API_KEY`） | 自动跳过 skipped |
| `heuristic` | 关键词兜底 keyword fallback | 永远在线 |

顺序 env `ENGINE_ORDER` 可覆（默认成本优先 cost-first）。
横评 compare：`python3 -m eval.sweep samples.jsonl --engine {rules,laya:sidecar,jev,heuristic}`。

## 校准与飞轮 Calibration & flywheel

```bash
python3 -m eval.sweep eval/samples_example.jsonl  # 合成样本验链路（不送拟合）
python3 -m eval.export --out eval/samples.jsonl   # 从审计+人工决议沉淀标签
python3 -m eval.calibrate --samples eval/samples.jsonl --out eval/calibration.json
```

- 温度拟合几十条即有效；微调需 500+ 条（届时开 Kaggle notebook，`MODEL_DIR` 切换 checkpoint，sweep A/B 回归）。
- `expected==review` 的行自动跳过（弃权类不可标定）；合成样本只验链路，不提交拟合表。

## API 与配置 API & config

| 端点 Endpoint | 用途 |
|---|---|
| `POST /api/review/submit` | 提交 `{kind,title,body,meta?}` |
| `POST /api/review/<id>/resolve` | 人审 `{outcome, actor}` |
| `GET /api/queue?state=` · `GET /api/stats` · `GET /api/health` | 队列 / 统计 / 引擎状态 |
| `GET /api/events` | SSE 实时流（hello + submitted/resolved/stats） |

| 环境变量 Env | 默认 Default | 含义 |
|---|---|---|
| `ENGINE_ORDER` | rules,laya:sidecar,jev,heuristic | 级联顺序 |
| `LAYA_SIDECAR_URL` / `LAYA_SIDECAR_TIMEOUT` | 127.0.0.1:8685 / 15s | sidecar 地址与超时（冷启动首推慢，宁宽） |
| `TYPESAFE_API_KEY` / `JEV_MODEL` | 空 / jev-latest | Jev 云端 key 与模型 |
| `LAYA_DEFAULT` / `LAYA_PRELOAD` / `LAYA_HEAD_MAX_LEN` | multilingual / 英+多 / 空 | 路由默认 / 预热列表 / 选项预算 |
| `MODEL_DIR` / `CALIBRATION_FILE` | Hub 官方 / eval/calibration.json | 微调 checkpoint / 温度表（热重载） |
| `PORT` / `CLEARANCE_DATA_DIR` | 8686 / data/ | 后端端口 / 数据目录 |

## 布局 Layout（根即产品）

```
├── clearance_core/   引擎插槽 + 网关 + 存储 + 服务
├── laya_sidecar/     Laya 独立决策服务（torch 隔离）
├── eval/             sweep + 拟合 + 沉淀 + 样本
├── web/              前端（pnpm + Vite + React + TS）
├── tests/            unittest（stdlib）   ·   data/ 运行时产物
├── start.sh          一键三进程            ·   reference/ 只读引用
```

动作注册表（7 个，幂等/risk 只在此声明）：`context.get`(L0)、`review.defer`(L1)、
`human.task.create`(L1)、`review.approve`(L2)、`review.reject`(L2)、`notify.send`(L2)、
`session.complete`(L0)。L3/L4 不存在——出现即转人工（故意缺席 by design）。

## 非目标 Non-goals

录制 / 桌面自动化 / 浏览器抓取 / 低代码画布 / Electron / VLM 截图进协议。

## 路线图 Roadmap

- [ ] 500+ 真实标签 → 首轮微调 + A/B 回归（`MODEL_DIR`）
- [ ] `cancelled` 态（人审超时/撤回，pending 不烂尾）
- [ ] 驳回结构化理由字段（可回流训练）
- [ ] 阈值预设（一键严格/均衡/宽松）
- [ ] Action 生命周期异步化（accepted/running → terminal，前端实时走）

## License / 历史 History

MIT（见 `LICENSE`）。旧 RPA 重资产封存于 `archive/apa-rpa` 分支；概念文档已全部
转为代码实现，行为以代码和测试为准。
