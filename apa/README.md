# APA — Agentic Process Automation

基于 [AIP 协议](../../README.md)（AI Interaction Protocol Kernel v0.1）的企业级智能流程自动化系统 POC。

设计文档：[`APA_Design_Document_v2.md`](../APA_Design_Document_v2.md)（§ 引用均指向该文档）

```
传统 RPA：  录制 → 规则 → 执行 → UI变化 → 崩溃 → 人工维护
APA：       语义事件 → AI决策（最小上下文）→ 可靠动作 → 协议级恢复 → 自愈
```

## 核心不变量

| 约束 | 含义 |
|---|---|
| P1 | 语义优先，永远不传遥测/DOM/截图 |
| P2 | AI 永远不持有最终执行权（Gateway 校验链不可绕过） |
| C3 | idempotency/risk 只来自 Action Registry，禁止消息携带 |
| C4 | 凭据禁止进入任何 AIP 消息 payload |
| C5/C6 | 大对象只传引用；VLM 在 Executor 本地终止 |
| C7 | Session 状态在 Gateway 侧，Decision Engine 无状态 |
| CoD-1/2/3 | 事件 data ≤ 4KB；context.get 禁 `["*"]`；ContextStore 由 Executor 持有 |

## 目录结构

```
apa/
├── registries/              # 标准 Action Registry（YAML，§9.3）
│   ├── core.yaml            #   context.* / human.*
│   ├── browser.yaml         #   browser.*
│   ├── desktop.yaml         #   desktop.*
│   └── api.yaml             #   api.* / erp.* / session.*
├── packages/
│   ├── apa-core/            # Gateway / Registry / Policy / Session / Audit / Rules
│   ├── apa-sdk-python/      # Executor 基类 / 自愈 / DryRun / 语义适配器 / 测试工具
│   └── apa-executors/       # BrowserExecutor (Playwright) / APIExecutor (httpx)
├── examples/
│   ├── hello-rpa/           # 最小可运行示例（真实浏览器 + 规则引擎，0 LLM）
│   ├── invoice-processing/  # v0.2 验收场景：发票 → 提取 → 写 ERP
│   └── po-approval/         # v0.3 验收场景：Process Mode 订单审批（批准/驳回分流）
├── plugins/dsh/             # dsh（DeepSeek Harness）决策引擎插件（TypeScript）
├── conformance/run.py       # APA-Profile 合规套件（20 用例）
└── tests/                   # pytest 单元 + 端到端
```

## 快速启动

```bash
# 10 分钟体验：语义适配器发现审批对话框 → 点击批准 → 提取结果 → 会话完成
python examples/hello-rpa/run.py --mock     # 无浏览器
python examples/hello-rpa/run.py            # 真实 Playwright headless

# APA-Profile 合规（CoD / C3 / C4 / I9 / 风险策略 / 幂等重试 …）
python conformance/run.py                   # → 20/20 passed

# 全部测试
python -m pytest tests/
```

环境要求见 [`QUICK_START.md`](QUICK_START.md)。

## 组件速览

### EmbeddedGateway（§13.2 模式 C）

```python
from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries

gw = EmbeddedGateway(
    "s_001",
    registry=load_registries("registries/browser.yaml"),
    policy=PolicyConfig(),                      # 默认按风险分级：L3+ → 人工
    identities={"executor": "browser_01", "agent": "rule_agent_001"},
)
gw.attach_executor(executor, "browser_01")      # executor 实现 on_message + peer
gw.attach_agent(agent, "rule_agent_001")
gw.run()
```

Gateway 校验链（§8.2）：信封 → 版本 → I9 来源绑定 → Session → 序列 →
Registry 查找 → Params Schema → 权限 → Session 状态 → C4 凭据扫描 →
风险策略 → 审计 → RetryScheduler → 转发。

### 自定义 Executor（30 分钟指南 §14.3）

继承 `apa_sdk.AIPExecutor`，只需实现两个方法：

```python
from apa_sdk import AIPExecutor

class MyExecutor(AIPExecutor):
    def _execute_action(self, name, params):
        if name == "my.action":                 # 在 my-registry.yaml 声明
            return True, {"done": True}
        return False, {"code": "action_not_supported_by_executor"}

    def start_observation(self):
        ...  # 通过 self.emit(name, data) 发语义事件（data ≤ 4KB，CoD-1）
```

协议层职责（幂等守卫、accepted 先回、错误分类、context.get）由基类免费提供。

### 规则决策引擎（§7.2 L0，0 Token）

```yaml
rules:
  - name: approve_small_order
    once: true                                  # 整个 Session 只执行一次
    if: { event: erp.order.approval_requested, data: { amount: { lt: 100000 } } }
    then: { action: browser.click, params: { target: approve-btn-1 } }
```

支持事件条件与 action_result 条件、金额比较（lt/le/gt/ge/eq/ne）、
`{{field}}` 模板插值。L1/L2（小模型/大模型）与 dsh 接入为后续阶段。

## 可交互入口

| 交互方式 | 命令 / 地址 |
|---|---|
| 真实浏览器自动化演示 | `python examples/hello-rpa/run.py`（Chromium 自动审批） |
| **网页人工审批（HITL）** | `python examples/human-approval/run.py` → 打开 `http://127.0.0.1:8690` 点「批准/驳回」，挂起的会话实时恢复并继续流转 |
| Studio 监控面板 | `python -m apa_core.studio --journals 'data/*.jsonl' [--tenant corp_x]` |
| 运行指标报告 | `python -m apa_core.analytics --journals 'data/*.jsonl'` |
| 人工任务查询 | `python -m apa_core.human_loop list --journal data/s.jsonl` |
| 外部决策端接入 | `ws://127.0.0.1:<port>`（Node 客户端已实测，见 plugins/dsh/tests） |

## v1.0 后续补全（Phase 5：感知与生态）

- [x] **VLM 视觉适配插槽**（§5.5，C6）：`apa_sdk.vision` —— 抽象基类 +
  OpenAI-compatible 实现（`APA_VISION_*` 环境变量）+ 脚本化 Fake；接入
  BrowserExecutor 感知降级链（DOM 解析 → VLM 本地分析）；**bounds 坐标
  在入协议前剥离**，截图只在 Executor 内存消费
- [x] **Schema 录制模式**（§B.1 问题 1）：`apa_sdk.recorder.SchemaRecorder`
  —— 记录动作触发的元素与页面状态，生成带 TODO 标注的 schema.yaml 草稿
  （事件命名需人工审核），可直接被 SemanticAdapter 加载验证
- [x] **HashiCorp Vault 对接**（§13.1）：KV v2 HTTP 后端
  （VAULT_ADDR / VAULT_TOKEN / VAULT_MOUNT），get/put/delete/list 全覆盖，
  与本地加密后端接口一致可互换

## v1.0 范围（§16.2：Policy 完整 / Vault / Analytics / 多租户）

- [x] **Credential Vault**（§12.1 第三层）：纯标准库加密存储（scrypt KDF +
  HMAC-CTR + encrypt-then-MAC，篡改/错钥检测），可选 Fernet 后端与 EnvVault；
  会话 TTL；`VaultManager` 注入门面 —— **C4**：auth 规格只含引用名，
  机密在 Executor 本地解析注入（schema 层 `additionalProperties: false`
  直接拒绝 literal 机密）
- [x] **API 凭据注入端到端**：api.http.* 的 `params.auth` → 本地解析 →
  Bearer 头注入；协议面帧与审计均无机密值
- [x] **Policy Engine 完整**：`deny_patterns` / `require_approval_patterns`
  通配规则、`principals_deny` 主体黑名单、规则级 `source` 条件
- [x] **速率限制**：`rate_limit_per_minute` 按来源滑动窗口（60s）→
  `rate_limited` 拒绝
- [x] **多租户隔离**（§12.1）：journal 全量记录 tenant、WS hello 租户绑定
  校验（不匹配 → UNAUTHORIZED）、Studio/Analytics 按 `--tenant` 过滤
- [x] **Analytics 服务**（§13.1）：journal → 会话状态分布/动作成功率/
  耗时 p50/p95/风险失败分布；CLI `python -m apa_core.analytics`；
  Studio `/api/analytics`
- [x] **MockERP 参考实现**（§B.3-4）：标准 REST 模拟 ERP（订单审批/
  发票/通知 + 可选 Bearer 认证），示例已统一复用

## v0.3 范围（§16.2：Process Mode / Desktop / 多 Bot / Studio）

- [x] **Process Mode 流程编排**（§10.2 模式 B）：`process.py` —— YAML 流程定义、
  `{{ }}` 模板与点路径条件（AST 白名单安全求值，拒绝任何调用/下标）、
  `ai_decision` 插槽节点（C1）、on_failure/goto 错误处理器、max_actions 预算守卫
  （C3：steps 中出现 idempotency/risk 加载即拒绝）
- [x] **验收场景** [`examples/po-approval`](examples/po-approval/)：
  订单审批流程（CoD 取数 → 金额分流批准/驳回 → ERP 落地 → 完成）双分支全绿
- [x] **DesktopExecutor**（§5.4）：可插拔后端 —— macOS `OsascriptBackend` +
  测试用 `MockDesktopBackend`；窗口观察事件（appeared/focused 去重）
- [x] **API 感知**：`APIExecutor.poll_once` 轮询观察（§B.3），新资源去重发事件
- [x] **WS 多 Bot 域路由**（§10.3）：executor hello 声明能力域，action 按
  Registry.executor_domain 精确路由；断线重连补发按域过滤
- [x] **APA-Studio v1**（§16.1 最小版）：零依赖单文件 —— 会话总览/游标/
  人工任务/审计尾部，`python -m apa_core.studio --journals 'data/*.jsonl'`

### v0.3 审视补漏（对已有构建的修正）

- **修复协议缺陷**：Gateway 自有回执此前未占用 `(session, gateway)` 流的连续
  seq，真实对端 Receiver 会判 stale 丢弃（被拒结果/人工任务回执静默丢失）。
  现在 `_assign_seq` 统一分配。
- **紧急熔断**（§12.4）：`gateway.abort()` —— 未决 action 标记 timeout、
  Session → CANCELLED、挂起任务关闭
- **expect 跟踪**（AIP §4.2）：Registry.expect 的动作 → 期望事件配对，
  `summary.expects_pending/satisfied`
- **Session 空闲过期**（K2）：`session_ttl_ms` 无活动超时 → SESSION_EXPIRED
- **多 Bot 身份**：identities 的 executor 侧支持列表成员校验（I9）
- **规则引擎防悬挂**：context.get 失败默认停止而非无限等待

## v0.1 范围（对照设计文档 §16.1 MVP）

- [x] `examples/hello-rpa` 一键跑通（mock 与真实浏览器双模式）
- [x] BrowserExecutor 基础动作（navigate/click/input/extract/select_option/wait_element/scroll/screenshot）
- [x] APA-Gateway 校验链 + 重试调度 + Session 状态机 + 审计
- [x] 纯规则 Decision Engine（无 LLM 依赖）
- [x] APA-Profile 合规套件（20 用例 > 要求的 ≥10）
- [x] 自定义 Executor 文档（本页「自定义 Executor」+ QUICK_START）
- [x] pytest 测试（单元 + MockPage 端到端 + 子进程冒烟）

## v0.2 范围（§16.2：LLM 接口 / Human-in-Loop / 持久化 / 文档域）

- [x] **LLM 决策接口**：OpenAI-compatible 客户端（默认 DeepSeek，`APA_LLM_*`
  环境变量）+ `parse_decision` 防御性解析
- [x] **Zero-LLM Cascade**（§7.2）：`CascadingAgent` L0 规则 → L1/L2 模型 →
  DE-5 不确定自动转人工；决策分布统计；预算保护
- [x] **WebSocket 独立网关**（§13）：`ws_gateway.WsGatewayServer` —— 绑定层
  hello/cursors/ping-pong（D1/D4），外部决策引擎经 WS 接入
- [x] **dsh 插件参考实现**：[`plugins/dsh/`](plugins/dsh/)（TypeScript +
  cordis，AIP TS SDK 直连网关，协议核心本地可 typecheck）
- [x] **Human-in-the-Loop 完整闭环**（§4.3）：human.task.create → SUSPENDED →
  `resolve_human_task` → RUNNING；任务 CLI
- [x] **Session 持久化**（§10.1）：JSONL 日志、游标精确恢复、终态 TTL 释放
- [x] **DocumentExecutor**（doc.extract_text/extract_fields/classify）+
  [`examples/invoice-processing`](examples/invoice-processing/)（发票 → 提取 →
  写 ERP，v0.2 验收场景）
- [x] 整值模板插值保留原生类型（number 参数直达 schema 校验）

**v0.2 显式不包含**：OCR/VLM 文档感知层、Desktop Executor、Process Mode 编排、
Vault 多租户。dsh 插件的 cordis 运行时联调需在 dsh 仓库侧执行（见插件 README）。

## License

Apache 2.0（衍生需署名）。协议基础 AIP Kernel v0.1 — MIT (emVisible/AIP)。