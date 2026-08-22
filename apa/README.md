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
│   └── invoice-processing/  # v0.2 验收场景：发票 → 提取 → 写 ERP
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