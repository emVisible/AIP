# APA — Agentic Process Automation
## 基于 AIP 协议的企业级智能流程自动化系统设计文档

> **版本：** v0.2  
> **日期：** 2026-08-20  
> **状态：** 开源项目规划文档（Pre-RFC）  
> **协议基础：** AIP Kernel v0.1（emVisible/AIP）  
> **AI 底座参考：** DeepSeek Harness v0.1（模型无关设计）  
> **对标目标：** UiPath Enterprise、ShadowBot、Microsoft Power Automate

---

## 目录

1. [背景与定位](#1-背景与定位)
2. [核心设计哲学](#2-核心设计哲学)
3. [系统架构](#3-系统架构)
4. [APA-Profile：AIP 协议扩展层](#4-apa-profileaip-协议扩展层)
5. [执行器（Executor）设计](#5-执行器executor设计)
6. [语义适配器（Semantic Adapter）](#6-语义适配器semantic-adapter)
7. [Decision Engine 集成规范](#7-decision-engine-集成规范)
8. [APA-Gateway 详细设计](#8-apa-gateway-详细设计)
9. [Action Registry — RPA 动作注册表](#9-action-registry--rpa-动作注册表)
10. [Session 与流程编排](#10-session-与流程编排)
11. [错误处理与自愈](#11-错误处理与自愈)
12. [安全与审计](#12-安全与审计)
13. [后端服务架构](#13-后端服务架构)
14. [开发者体验与 SDK](#14-开发者体验与-sdk)
15. [对标分析与差异化](#15-对标分析与差异化)
16. [开源项目规划](#16-开源项目规划)
17. [附录 A：完整消息序列示例](#17-附录-a完整消息序列示例)
18. [附录 B：已知问题与设计权衡](#18-附录-b已知问题与设计权衡)

---

## 1. 背景与定位

### 1.1 传统 RPA 的三个根本性矛盾

**矛盾一：自动化 vs 脆弱性**

录制式 / 规则式 RPA 在 UI 结构稳定时效率极高，但任何界面改动都可能导致整个流程崩溃。Forrester 2025 调研显示，企业 RPA 维护成本占总拥有成本的 40%–60%。AI 接入被寄望于解决这一问题，但引出了第二个矛盾。

**矛盾二：AI 接入 vs 成本可控**

主流产品的"AI 集成"通常是将完整 DOM、截图或聊天历史一次性投喂 LLM，导致：Token 消耗爆炸（单次决策 5000–50000 token 是常态）、长上下文幻觉风险增加、推理延迟不可接受。AI 并未降低 RPA 的成本，反而引入了新的不确定性。

**矛盾三：集成 vs 协议碎片化**

AI 决策引擎与 RPA 执行器之间没有标准的运行时通信协议。MCP 解决"AI 能调用什么工具"，A2A 解决"多 Agent 如何协作"，但"决策引擎逐步驱动执行器完成任务"这条边界上没有成熟标准，导致每个产品都实现了自己的私有协议，执行器无法互换，审计无法跨产品追踪。

### 1.2 APA 的定位

**APA（Agentic Process Automation）** 是一个以 AIP 协议为通信骨干的企业级智能流程自动化平台。

```
传统 RPA：  录制 → 规则 → 执行 → UI变化 → 崩溃 → 人工维护
APA：       语义事件 → AI决策（最小上下文）→ 可靠动作 → 协议级恢复 → 自愈
```

APA 的核心赌注只有一个：**将 AI 决策与 RPA 执行的边界用一个最小化、可验证的开放协议固定下来**。协议固定后，决策引擎可以是任意 AI（规则、小模型、LLM、人工），执行器可以是任意自动化后端（浏览器、桌面、API、ERP），两者可以独立演进、独立替换。

### 1.3 APA 不是什么

在规划开源项目之前，明确边界同等重要：

| APA 不做 | 理由 |
|---|---|
| 不重造 MCP | 工具能力发现由 MCP 负责，APA Action 可路由到 MCP 网关 |
| 不重造 A2A | 多 Agent 协作由 A2A 负责，APA Session 可嵌入 A2A Task |
| 不内置工作流引擎 | 长流程编排可接入现有引擎（Temporal、Airflow），APA 负责单次执行边界 |
| 不绑定特定 LLM | Decision Engine 是可替换插槽，非 APA 核心 |
| 不做低代码可视化编辑器（v1） | 编辑器是生态产品，核心先做稳 |

### 1.4 命名约定

| 术语 | 含义 |
|---|---|
| **APA** | Agentic Process Automation — 本平台总称 |
| **AIP** | AI Interaction Protocol — emVisible/AIP Kernel v0.1 |
| **APA-Gateway** | AIP Gateway 的 RPA 专用实现 |
| **APA-Executor** | 各类 RPA 执行器的 AIP 适配层（浏览器/桌面/API/文档） |
| **Semantic Adapter** | 将原始自动化观察翻译为 AIP 语义事件的适配层 |
| **Decision Engine** | AIP 决策引擎插槽，可接入任意 AI 或规则系统 |
| **APA-Studio** | 管理前端（监控/审计/配置，非低代码编辑） |
| **dsh** | DeepSeek Harness，APA 推荐的 Decision Engine 参考实现之一 |

---

## 2. 核心设计哲学

### 2.1 三个不妥协的原则

**原则 P1：语义优先，永远不传遥测**

执行器向决策引擎传送的必须是业务语义，而不是原始观察。

```
❌  { button_x: 321, button_y: 402, dom_node: "<button id='btn-83'>..." }
✅  { name: "approval.dialog.appeared", data: { context: "ctx_po_001",
     available_actions: ["approve", "reject", "defer"] } }
```

这不只是性能优化——它是让 AI 在结构化状态空间而不是 UI 噪声中做决策的前提。语义边界也是 Executor 的合约：Executor 的职责是把物理世界的变化翻译成业务语义，而不是把 DOM 转发给 AI。

**原则 P2：AI 永远不持有最终执行权**

AIP 安全不变量（I9 + I10）的直接推论：AI 的输出是不可信输入，必须经过 Gateway 的 Schema 校验、Registry 查找、策略校验，然后才能到达执行器。这条路径不可绕过，无论 AI 置信度多高。

这解决了一个实际问题：LLM 幻觉出一个不存在的动作名，或者构造出危险的参数，Gateway 的前置校验会在执行前 reject 掉，而不是让执行器在现实中产生副作用后才发现。

**原则 P3：最小充分上下文，而非最小消息体积**

优化目标是"每次决策所需的最小充分上下文"，不是"最短消息"。一个正确的 5KB 决策胜过一个错误的 200 字节决策。

实现机制是 Context-on-Demand（AIP §9.2）：事件只携带语义摘要和上下文引用，Decision Engine 主动按需 fetch 它实际需要的字段。这与 LLM 的工具调用模式完全自然，不需要新的抽象。

### 2.2 架构约束（不可违反的设计边界）

这些约束比任何功能更重要，是本文档所有设计决策的上级规则：

| 约束 ID | 内容 |
|---|---|
| **C1** | Decision Engine 是可替换插槽：规则引擎、任意 LLM、人工，都是合法的 Decision Engine |
| **C2** | Executor 是可替换插槽：Browser / Desktop / API / 自定义，都是合法的 Executor |
| **C3** | Action 的幂等性声明在 Registry 中，禁止在动作消息中携带 |
| **C4** | 凭据（密码、Token、Cookie）禁止出现在任何 AIP 消息 payload 中 |
| **C5** | Context 大对象只能以引用传递，禁止直接内联到事件 payload |
| **C6** | Vision/VLM 分析在 Executor 本地同步完成，结果以语义事件发出；禁止将截图通过 AIP 协议发往 Decision Engine |
| **C7** | Session 状态存储在 Gateway 侧，Decision Engine 不持有任何执行状态 |

> **C6 特别说明**：将截图通过 AIP action/result 路径发给 AI 分析，单次延迟会达到 2–5 秒，且每帧图像约 200KB，完全背离 AIP 的低上下文原则。VLM 是 Executor 内部的感知手段，其输出（语义元素列表）才是进入协议的数据。

---

## 3. 系统架构

### 3.1 分层架构全景

```
┌──────────────────────────────────────────────────────────────────────┐
│                        APA-Studio（管理界面）                          │
│  流程监控 · 实时日志 · 审计追踪 · Bot 管理 · 成本看板 · 策略配置          │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ REST API / SSE
┌────────────────────────────────▼─────────────────────────────────────┐
│                        APA 控制平面（Control Plane）                   │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │  Process     │  │  Scheduler   │  │  Credential  │  │  Action  │  │
│  │  Registry    │  │  Service     │  │  Vault       │  │  Registry│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────┘  │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │  Policy      │  │  Audit       │  │  Analytics   │               │
│  │  Engine      │  │  Service     │  │  Service     │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │              AIP 数据平面             │
              │                                     │
┌─────────────▼────────────┐    ┌───────────────────▼────────────────┐
│      APA-Gateway          │    │         Decision Engine（插槽）     │
│                           │    │                                    │
│  · AIP 消息路由           │    │  可接入：                          │
│  · seq/cursor 维护        │◄──►│  · 确定性规则引擎（零 LLM）         │
│  · 幂等性守卫             │    │  · dsh（DeepSeek Harness）         │
│  · 策略前置校验           │    │  · 任意 OpenAI-compatible LLM      │
│  · 重试调度器             │    │  · 自定义 Python/TS Agent          │
│  · Session 状态机         │    │  · Human-in-the-Loop 代理          │
│  · 审计事件流             │    │                                    │
└─────────────┬─────────────┘    └────────────────────────────────────┘
              │ AIP over WebSocket
   ┌──────────┼───────────────────────────────────────┐
   │          │                                       │
┌──▼──────────┐  ┌─────────────────┐  ┌──────────────▼───────────────┐
│  Browser    │  │  Desktop        │  │  API / ERP                   │
│  Executor   │  │  Executor       │  │  Executor                    │
│             │  │                 │  │                              │
│  Playwright │  │  Win32 Acc.API  │  │  REST/SOAP/gRPC              │
│  内置 VLM   │  │  AT-SPI(Linux)  │  │  SAP BAPI / Oracle EBS      │
│  语义适配器 │  │  内置 VLM fallb │  │  Salesforce API              │
└─────────────┘  └─────────────────┘  └──────────────────────────────┘

[每个 Executor 内部均包含：语义适配器 + AIP Peer + ContextStore + 凭据注入层]
```

### 3.2 关键数据流（带约束标注）

以"ERP 采购审批"为例，标注每个环节触发的架构约束：

```
物理世界（浏览器渲染出审批对话框）
    │
    ▼ [Executor 内部，不进入 AIP 协议]
Playwright page event → DOM 解析 → 可交互元素提取
    │                              ↑
    │                    若 DOM 无法解析 → 本地 VLM 分析截图（C6：VLM 在此终止）
    │
    ▼ [语义适配器，CoD-1：只传引用]
大量状态 → APAContextStore.put("ctx_po_001", {...}) → 返回引用字符串
    │
    ▼ [AIP event，< 4KB]
{ name: "approval.dialog.appeared",
  data: { context: "ctx_po_001",           ← 引用，不是对象（C5）
          available_actions: ["approve","reject","defer"],
          risk_hint: "L2" } }
    │
    ▼ [APA-Gateway]
seq 校验 → source 验证 (I9) → 路由到 Decision Engine
    │
    ▼ [Decision Engine — C7：不持有 Session 状态]
规则检查 → 未命中 → context.get(fields=["amount"]) → 获取 1 个字段 → 规则命中 → approve
    │
    ▼ [AIP action]
{ name: "erp.order.approve",
  params: { order_id: "PO-5678", approver: "apa_system" } }
    │                               ← 不含 idempotency/risk（C3）
    ▼ [APA-Gateway，P2：AI 不持有执行权]
① Registry 查找 ✓  ② Schema 校验 ✓  ③ 权限 ✓
④ 风险 L2 → Policy 自动放行 ✓  ⑤ 凭据扫描 clean（C4）✓
⑥ 审计写入 → 转发 Executor
    │
    ▼ [Executor 执行，凭据从 Vault 本地注入，不经过协议（C4）]
Playwright.click("#approve-btn") → result: accepted → running → ok
```

---

## 4. APA-Profile：AIP 协议扩展层

AIP Kernel v0.1 的扩展机制是 Profile（§9）：通过 Action Registry 和事件命名空间扩展，不修改协议核心（4 消息类型 / 9 信封字段保持不变）。

### 4.1 事件命名空间（APA-RPA Profile）

命名规则：`{domain}.{entity}.{state_change}`，事件表达已发生的事实（完成时态）。

```
# ── 浏览器域（browser.*）
browser.page.loaded            { url, title, context }
browser.page.changed           { url, title, from_url, context }
browser.element.appeared       { semantic_id, role, text, enabled, context }
browser.element.disappeared    { semantic_id, context }
browser.dialog.opened          { kind: "confirm|alert|prompt|custom",
                                  message_summary, context }
browser.download.completed     { filename, size_bytes, local_path_ref }
browser.error.occurred         { error_type, url, context }

# ── 桌面域（desktop.*）
desktop.window.appeared        { app_name, title, pid, context }
desktop.window.focused         { app_name, title, context }
desktop.window.closed          { app_name, title }
desktop.notification.appeared  { app, summary, context }
desktop.file.created           { path_ref, size_bytes }

# ── 文档域（document.*）
document.processing.started    { doc_id, doc_type, context }
document.processing.complete   { doc_id, result_ref }
document.validation.failed     { doc_id, field, error_code }

# ── 业务域（erp.* / crm.* / 自定义，由各 Executor 扩展声明）
erp.order.approval_requested   { context, available_actions, risk_hint }
erp.order.status_changed       { order_id, from, to, context }
erp.invoice.received           { invoice_id, context }
form.validation.failed         { field, error_code, context }

# ── 系统控制域（bot.*）
bot.session.started            { session_id, process_id, executor_ids }
bot.executor.ready             { executor_id, capabilities }
bot.executor.error             { executor_id, error_type, recoverable }

# ── 人工干预域（human.*）
human.task.created             { task_id, assignee, due_at, context }
human.task.completed           { task_id, outcome, actor, comment, context }
human.task.expired             { task_id, escalated_to }
```

**禁止项：**
- 禁止命令式命名（`please_click`、`do_approve` 是 action，不是 event）
- 禁止将 bot.session.heartbeat 用于 AIP 绑定级 ping/pong（两者不同层）
- 业务域事件（`erp.*`、`crm.*`）只由该 domain 的 Executor 发出，禁止 Decision Engine 发出

### 4.2 Context-on-Demand 实施规范

**规则 CoD-1：事件 data 体积上限 4KB**

事件 `payload.data` JSON 序列化大小不超过 4KB。超出返回 `INVALID_MESSAGE`。

4KB 的依据：足以容纳 20–30 个业务字段摘要，不对 LLM 单次 prompt 造成显著 Token 消耗。

**规则 CoD-2：ContextStore 字段级访问控制**

Decision Engine 通过 `context.get` 只能获取声明的字段，禁止传 `fields: ["*"]`。

**规则 CoD-3：ContextStore 由 Executor 持有**

ContextStore 在 Executor 进程内（本地内存或 Session 级 Redis），不在协议层传输。Gateway 只路由 `context.get` action，不持有任何上下文对象。

```python
class APAContextStore:
    def put(
        self,
        ref: str,                    # 格式强制：ctx_{session_id}_{name}
        data: dict,
        ttl_ms: int = 3_600_000,
        acl: dict | None = None,     # { field: [principal_id, ...] }
    ) -> str: ...

    def get(
        self,
        ref: str,
        fields: list[str],           # 不允许 ["*"]
        principal: str,
    ) -> dict: ...

    def snapshot(self, ref: str) -> dict: ...   # 审计用，需审计权限
    def invalidate(self, ref: str) -> None: ...
```

### 4.3 Human-in-the-Loop Profile

将人工干预建模为标准 AIP Action，不引入新消息类型：

```
action: human.task.create
  params:
    assignee_role: string          # 角色（由任务系统分配具体人）
    task_type: "approval"|"review"|"exception"
    context_ref: string
    available_outcomes: string[]
    due_at: number                 # epoch ms
    priority: "low"|"normal"|"high"|"urgent"
  idempotency: required
  risk: L1        # ← 此 action 本身是通知操作，高风险是后续业务 action

event: human.task.completed
  data: { task_id, outcome, actor, comment, context }

event: human.task.expired
  data: { task_id, escalated_to }
```

Session 在 `human.task.create` 执行后进入 `SUSPENDED`，Gateway 保持游标，Bot 进程不需要保持连接，人工完成后从 cursor+1 恢复。


---

## 5. 执行器（Executor）设计

### 5.1 执行器分类

| Executor | 目标场景 | 核心依赖 | 感知策略 |
|---|---|---|---|
| **BrowserExecutor** | Web 应用、SaaS 系统、内网门户 | Playwright | DOM 解析 → VLM fallback |
| **DesktopExecutor** | Win32/WPF/Qt 桌面应用 | pywinauto / AT-SPI | Accessibility API → OCR → VLM |
| **APIExecutor** | REST/SOAP/gRPC 服务 | httpx / zeep | 无感知层，直接结构化 |
| **DocumentExecutor** | PDF/Word/Excel/扫描件 | pdfplumber / python-docx | OCR + LLM 提取 |
| **ERPExecutor** | SAP / Oracle / 自研 ERP | 各 ERP SDK | ERP API + Web fallback |
| **HumanTaskExecutor** | 人工干预代理 | WebSocket 推送 | 接收事件，不主动感知 |

### 5.2 Executor 基类规范

所有 Executor 继承 `AIPExecutor` 基类。基类处理全部协议层职责，子类只需实现业务层。

```python
# apa/executor/base.py
class AIPExecutor(ABC):
    """
    协议层职责（基类处理，子类禁止重写）：
      · AIP Peer 管理（seq / cursor / session）
      · duplicate 检测 / gap 处理
      · 幂等性守卫（executed_action_ids）
      · accepted 先行回复（AIP §4.5）
      · 错误分类（业务失败 → result.failed / 协议异常 → error）

    业务层职责（子类实现）：
      · _execute_action(name, params) → (success: bool, data: dict)
      · _on_session_start() / _on_session_end()
      · start_observation()  ← 启动感知循环，持续 send_event
    """

    def __init__(self, source: str, session_id: str, transport: Transport):
        self.peer = AIPPeer(source=source, session_id=session_id,
                            transport=transport)
        self.context_store = APAContextStore(session_id=session_id)
        self._executed: dict[str, tuple[str, str]] = {}  # action_id → (status, result_id)

    async def on_message(self, raw: dict) -> None:
        kind, msg = self.peer.handle(raw)
        if kind == "duplicate":
            if msg.type == "action":
                self._replay_outcome(msg.id)
            return
        if kind in ("stale", "gap"):
            return  # Gateway 已处理序列错误
        if kind != "accept":
            return
        if msg.type == "action":
            await self._dispatch_action(msg)

    async def _dispatch_action(self, msg: AIPMessage) -> None:
        action_id = msg.id
        name = msg.payload["name"]
        params = msg.payload.get("params", {})

        # 幂等性守卫（AIP I2）
        if action_id in self._executed:
            status, original_id = self._executed[action_id]
            self.peer.send_result(status, in_reply_to=action_id,
                                  duplicate=True, original_result_id=original_id)
            return

        # 长操作先回 accepted（AIP §4.5）
        self.peer.send_result("accepted", in_reply_to=action_id)

        try:
            success, data = await self._execute_action(name, params)
            status = "ok" if success else "failed"
        except ExecutorPreconditionError as e:
            result_id = self.peer.send_result("rejected", in_reply_to=action_id,
                                              code=e.code)
            self._executed[action_id] = ("rejected", result_id)
            return
        except Exception as e:
            status, data = "failed", {"code": "internal_error", "detail": str(e)}

        result_id = self.peer.send_result(
            status, in_reply_to=action_id,
            data=data if status == "ok" else None,
            code=data.get("code") if status != "ok" else None,
        )
        self._executed[action_id] = (status, result_id)

    @abstractmethod
    async def _execute_action(self, name: str, params: dict) -> tuple[bool, dict]:
        """
        执行具体动作。前置条件（Registry/权限/策略）已由 Gateway 完成校验。
        返回 (True, result_data) 或 (False, {"code": "..."})。
        """

    @abstractmethod
    async def start_observation(self) -> None:
        """启动感知循环，通过 self.peer.send_event() 持续发出语义事件"""
```

### 5.3 BrowserExecutor

```python
class BrowserExecutor(AIPExecutor):
    """
    基于 Playwright 的 Web 自动化执行器。
    VLM 在 Executor 内部使用，产物是语义元素列表，不进入 AIP 协议（C6）。
    """

    def __init__(self, source, session_id, transport,
                 vision_model: VisionAdapter | None = None):
        super().__init__(source, session_id, transport)
        self.semantic_adapter = BrowserSemanticAdapter(vision_model)

    async def _on_page_load(self, page: Page) -> None:
        raw_state = await self._capture_page_state(page)
        semantic = await self.semantic_adapter.lift(raw_state)
        # semantic: 可交互元素的语义列表，不含原始 DOM（C5）

        ctx_ref = self.context_store.put(
            f"ctx_page_{self.peer.session_id}_{id(page)}",
            {"url": page.url, "title": await page.title(),
             "elements": semantic.elements, "forms": semantic.forms},
        )
        self.peer.send_event("browser.page.loaded", {
            "url": page.url,
            "title": await page.title(),
            "context": ctx_ref,
        })

    async def _execute_action(self, name: str, params: dict) -> tuple[bool, dict]:
        match name:
            case "browser.navigate":
                await self.page.goto(params["url"],
                    wait_until=params.get("wait_for", "networkidle"))
                return True, {}

            case "browser.click":
                locator = self._resolve_target(params["target"])
                await locator.click(force=params.get("force", False))
                return True, {}

            case "browser.input":
                locator = self._resolve_target(params["target"])
                if params.get("clear_first", True):
                    await locator.clear()
                await locator.fill(params["value"])
                return True, {}

            case "browser.extract":
                result = {}
                for field, selector in params["selectors"].items():
                    result[field] = await self.page.locator(selector).inner_text()
                out_ref = params.get("output_context",
                                     f"ctx_extract_{self.peer.session_id}")
                self.context_store.put(out_ref, result)
                return True, {"output_context": out_ref}

            case "context.get":
                data = self.context_store.get(
                    params["ref"], params["fields"],
                    principal=self.peer.source,
                )
                return True, {"ref": params["ref"], "data": data}

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    def _resolve_target(self, target: str) -> Locator:
        """
        目标解析优先级：
        1. data-apa-id 属性（推荐：在目标应用中注入，最稳定）
        2. aria-label / role + text
        3. CSS selector（兜底，最脆弱）
        """
        if target.startswith("#") or target.startswith("."):
            return self.page.locator(target)
        return (self.page.locator(f"[data-apa-id='{target}']")
                .or_(self.page.get_by_label(target))
                .or_(self.page.get_by_role("button", name=target)))
```

### 5.4 DesktopExecutor

```python
class DesktopExecutor(AIPExecutor):
    """
    桌面自动化执行器。感知优先级：
    1. Windows Accessibility API (pywinauto / UIA)
    2. Linux AT-SPI (pyatspi)
    3. OCR（Tesseract / PaddleOCR）
    4. VLM 语义理解（最慢，仅当前三者均失败）
    """

    async def _lift_window_state(self, window_handle) -> SemanticWindowState:
        # Level 1: Accessibility API
        try:
            elements = self.acc_api.get_interactive_elements(window_handle)
            if elements:
                return SemanticWindowState.from_accessibility(elements)
        except AccessibilityAPIError:
            pass

        # Level 2: OCR
        screenshot = self._capture_window(window_handle)
        try:
            return SemanticWindowState.from_ocr(
                await self.vision_adapter.ocr(screenshot))
        except OCRError:
            pass

        # Level 3: VLM（本地分析，不走 AIP 协议）
        if self.vision_adapter.has_vlm:
            async with asyncio.timeout(5.0):
                return await self.vision_adapter.understand_screen(screenshot)

        raise ExecutorPreconditionError("perception_failed",
            "All perception methods failed for this window")
```

### 5.5 VLM 在 Executor 中的正确使用方式

> 这是 C6 约束的详细展开，与 v0.1 文档的最大差异。

**错误模式（禁止）：**

```
截图 → 通过 AIP action 发往 Decision Engine → LLM 分析 → 回传坐标 → Executor 执行
问题：① 单次延迟 2–5 秒  ② 截图 ~200KB 违反 C5  ③ 坐标驱动绕过语义层违反 P1
```

**正确模式：**

```
截图 → Executor 本地 VLM 分析 → 语义元素列表 → AIP event（< 4KB）
好处：① VLM 延迟在 Executor 内消化  ② 协议只传语义  ③ VLM 可随时替换
```

```python
class VisionAdapter:
    """
    Executor 内部 VLM 适配层。
    此类不发出任何 AIP 消息，只返回 SemanticWindowState。
    """
    async def understand_screen(self, screenshot: bytes) -> SemanticWindowState:
        b64 = base64.b64encode(screenshot).decode()
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": SCREEN_UNDERSTANDING_PROMPT},
            ]}],
            response_format={"type": "json_object"},
        )
        raw = json.loads(resp.choices[0].message.content)
        return SemanticWindowState(**raw)
        # SemanticWindowState.elements[].bounds 坐标保留在 Executor 内
        # 不进入 AIP 协议（C6）
```

---

## 6. 语义适配器（Semantic Adapter）

语义适配器是 APA 中最需要投入设计精力的地方，其质量决定了整个系统的 AI 决策质量，也是开源社区最重要的贡献入口。

### 6.1 适配器的职责边界

```
物理世界的观察              语义适配器               AIP 语义事件
─────────────────          ─────────────           ─────────────────
DOM node #83929   →  识别业务角色（审批对话框）→  approval.dialog.appeared
button.x=321      →  映射到可执行动作           →  available_actions: ["approve"]
API {status:400}  →  翻译错误语义              →  erp.order.validation.failed
文件变化事件       →  过滤无关变化              →  document.processing.complete
```

### 6.2 Schema-Driven 适配：解决"如何知道提取什么"

这是传统 RPA 没有回答好的问题。APA 的解法：**Executor 启动时声明 ElementSchema，适配器根据 Schema 做模式匹配**，而不是每次从零分析 DOM。

```yaml
# executors/erp-portal/schema.yaml
app:
  name: "ERP采购门户"
  url_pattern: "erp.corp.com/purchase/*"

semantic_patterns:
  approval_dialog:
    trigger:
      element: { role: "dialog" }
      contains: [ { text_pattern: "审批", role: "heading" } ]
    emit:
      event: "erp.order.approval_requested"
      data_mapping:
        order_id: { selector: "[data-order-id]" }
        amount:   { selector: ".order-amount", transform: "parse_currency" }
        vendor:   { selector: ".vendor-name" }
      available_actions:
        - name: "approve"
          trigger: { role: "button", text_pattern: "批准|同意|通过" }
          maps_to_action: "erp.order.approve"
        - name: "reject"
          trigger: { role: "button", text_pattern: "拒绝|驳回" }
          maps_to_action: "erp.order.reject"

  order_list:
    trigger:
      url_pattern: "/purchase/pending"
      element: { role: "grid", aria_label_pattern: "待处理订单*" }
    emit:
      event: "erp.order.list.loaded"
      data_mapping:
        count: { selector: ".record-count", transform: "parse_int" }
```

Schema 文件驱动适配，开发一个新 Executor 时通常只需编写 YAML，无需修改 Python 代码。

### 6.3 事件防抖（Event Coalescer）

防止高频 UI 变化产生事件风暴淹没 Decision Engine：

```python
class EventCoalescer:
    """同名事件在 debounce 窗口内只发一次"""
    def __init__(self, debounce_ms: int = 500):
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._debounce_ms = debounce_ms

    async def submit(self, event_name: str, event_fn: Callable) -> None:
        if event_name in self._pending:
            self._pending[event_name].cancel()
        handle = asyncio.get_event_loop().call_later(
            self._debounce_ms / 1000,
            lambda: asyncio.create_task(event_fn()),
        )
        self._pending[event_name] = handle
```

---

## 7. Decision Engine 集成规范

Decision Engine 是 APA 的可替换插槽（C1）。APA 不规定其内部实现，只规定 AIP 行为契约。

### 7.1 五条行为契约

```
DE-1: 只消费 terminal result（ok/failed/timeout/rejected）
      accepted/running 是进度报告，不触发业务决策

DE-2: 按需 fetch 上下文，禁止本地缓存 Session 状态（C7）
      每次决策从当前事件 + context.get 结果出发

DE-3: action 只携带 name / target / params
      禁止在 action 中携带 idempotency / risk（C3）

DE-4: 只在 error.retry.allowed=true 时发起重试，且复用同一 action.id

DE-5: 不确定时创建 human.task，而不是猜测或盲目重试
```

### 7.2 Zero-LLM Cascade（决策分级路由）

```
事件到达
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  L0：确定性规则引擎（0 Token，< 1ms）                        │
│  · 状态机转换 · 金额阈值 · 白名单 · 重复操作检测             │
│  目标覆盖率：30–50%（视业务规范化程度）                      │
└──────────────────────────┬─────────────────────────────────┘
                           │ 规则未命中
                           ▼
┌────────────────────────────────────────────────────────────┐
│  L1：小模型快速判断（100–500 Token/决策）                    │
│  · 标准化 NL 理解 · 历史相似决策 · 低风险常规判断           │
│  · Think Non 模式，低延迟                                  │
│  目标覆盖率：35–50%                                        │
└──────────────────────────┬─────────────────────────────────┘
                           │ 置信度 < threshold
                           ▼
┌────────────────────────────────────────────────────────────┐
│  L2：大模型深度推理（500–3000 Token/决策）                   │
│  · 模糊场景 · 多步推理 · 异常处理 · 文档理解               │
│  目标覆盖率：10–20%                                        │
└──────────────────────────┬─────────────────────────────────┘
                           │ 输出 uncertain 或超出权限
                           ▼
┌────────────────────────────────────────────────────────────┐
│  L3：Human-in-the-Loop（< 2% 为目标）                       │
│  · human.task.create → Session SUSPENDED → 人工完成后恢复  │
└────────────────────────────────────────────────────────────┘
```

**成本说明（诚实的数字）：**

AIP Benchmark 在**模拟测试**中显示 AIP 方案比长上下文 Agent 便宜 13x–93x。真实业务的节省幅度取决于规则覆盖率和上下文大小。**应在首批真实流程跑通后用实测数字替换此处的理论估算**。

在规则 40%、小模型 45%、大模型 15% 的混合场景下，相比全量 LLM 方案，保守预期节省 **8x–30x**。

### 7.3 dsh 接入规范（Cordis 插件）

```typescript
// apa-dsh-plugin/index.ts
export default class APADecisionPlugin extends Plugin {
    static inject = ["llm", "tools"]

    async provide(ctx: Context) {
        const aipPeer = new AIPPeer({
            source: "dsh_agent_001",
            sessionId: ctx.config.sessionId,
            transport: new WsClientTransport(ctx.config.gatewayUrl),
        })

        aipPeer.on("event", async (event) => {
            await this.decide(ctx, aipPeer, event)
        })

        // 只处理 terminal result（DE-1）
        aipPeer.on("result", async (result) => {
            const { status } = result.payload
            if (["ok", "failed", "timeout", "rejected"].includes(status)) {
                await this.onTerminalResult(ctx, aipPeer, result)
            }
        })

        await aipPeer.connect()
    }

    async decide(ctx: Context, peer: AIPPeer, event: AIPEvent): Promise<void> {
        const { name, data } = event.payload

        // L0：规则引擎
        const ruleResult = this.ruleEngine.evaluate(name, data)
        if (ruleResult) {
            peer.sendAction(ruleResult.action, ruleResult.params)
            return
        }

        // L1/L2：模型决策（事件 data < 4KB，不包含完整上下文）
        const response = await ctx.llm.complete(
            buildDecisionPrompt(name, data),
            { tools: [this.contextGetTool(peer)],
              think: this.selectThinkMode(name) },
        )
        peer.sendAction(response.action, response.params)
    }

    private contextGetTool(peer: AIPPeer): ToolDefinition {
        return {
            name: "context_get",
            description: "按需获取业务上下文中的特定字段（CoD）",
            parameters: {
                ref: { type: "string" },
                fields: { type: "array", items: { type: "string" } },
            },
            handler: async ({ ref, fields }) =>
                peer.sendActionAndWait("context.get", { ref, fields }),
        }
    }
}
```

---

## 8. APA-Gateway 详细设计

Gateway 是 APA 安全与可靠性的唯一守卫线，所有 AIP 消息必须经过 Gateway，没有例外。

### 8.1 职责边界（明确且完整）

```
Gateway 负责：                         Gateway 不负责：
✓ AIP 信封校验（v/type/seq/source）   ✗ 业务逻辑判断
✓ 序列维护（cursor 更新）             ✗ 上下文存储（在 Executor 侧）
✓ 幂等性守卫（action dedup）          ✗ 决策（Decision Engine 负责）
✓ Action Registry 查找               ✗ 流程定义（Process Engine 负责）
✓ Params Schema 校验                 ✗ 模型选择（Decision Engine 负责）
✓ 策略校验（风险分级 / 权限）
✓ 凭据扫描（I10）
✓ 审计日志写入
✓ 重试调度（幂等动作的超时重试）
✓ Session 状态机
✓ Human Task 挂起/恢复
```

### 8.2 消息处理主流程

```python
class APAGateway:
    """每个活跃 Session 持有一个 Gateway 实例"""

    def receive(self, side: Literal["executor","agent"], raw: dict) -> list[dict]:
        # 阶段 1：信封校验
        msg, err = validate_envelope(raw)
        if err:
            return [make_error("INVALID_MESSAGE", detail=err)]

        # 阶段 2：版本协商
        if msg.v != 1:
            return [make_error("UNSUPPORTED_VERSION")]

        # 阶段 3：身份验证（AIP I9）
        if not self._verify_source(side, msg.source):
            return [make_error("UNAUTHORIZED")]

        # 阶段 4：Session 有效性
        if not self._check_session(msg.session):
            return [make_error("SESSION_EXPIRED")]

        # 阶段 5：序列检查（AIP §5.4）
        seq_result = self._check_sequence(msg)
        match seq_result:
            case "duplicate":
                return self._handle_duplicate(msg)
            case "gap" | "stale":
                return [make_error("SEQ_OUT_OF_ORDER")]
            case "ok":
                self._advance_cursor(msg)

        # 阶段 6：类型分发
        match msg.type:
            case "event":   return self._route_event(msg)
            case "action":  return self._validate_action(msg)
            case "result":  return self._process_result(msg)
            case "error":   return self._handle_error_msg(msg)

    def _validate_action(self, msg: AIPMessage) -> list[dict]:
        """动作前置校验链（任一步骤失败 → rejected，不执行）"""
        name = msg.payload["name"]
        params = msg.payload.get("params", {})

        entry = self.registry.get(name)
        if not entry:
            return [make_result("rejected", msg.id, code="action_not_registered")]

        errors = entry.validate_params(params)
        if errors:
            return [make_result("rejected", msg.id,
                                code="invalid_params", detail=errors)]

        if not self._check_permission(msg.source, entry):
            return [make_result("rejected", msg.id, code="permission_denied")]

        if not self._check_session_allows(entry):
            return [make_result("rejected", msg.id, code="session_state_mismatch")]

        if detect_credentials(params):           # C4
            self.audit.alert("credential_in_payload", msg)
            return [make_result("rejected", msg.id, code="credential_in_payload")]

        policy_result = self.policy.evaluate(msg, entry)
        if policy_result == PolicyDecision.REJECT:
            return [make_result("rejected", msg.id, code="policy_violation")]
        if policy_result == PolicyDecision.REQUIRE_HUMAN:
            return self._create_human_task_and_suspend(msg, entry)

        self.audit.log_action(msg, entry, verdict="permitted")
        self.retry_scheduler.schedule(msg, entry)
        return [msg.to_dict()]  # 转发给 Executor
```

### 8.3 重试调度器

```python
class RetryScheduler:
    """
    只重试 idempotency=required 的动作（AIP §6.5）。
    重试复用同一 action.id（Executor 侧通过 dedup 返回存储结果）。
    """
    def schedule(self, action_msg: AIPMessage, entry: RegistryEntry) -> None:
        if entry.idempotency != "required" or entry.retries <= 0:
            return
        self._set_timer(action_msg, entry, attempt=0)

    def _set_timer(self, msg, entry, attempt: int) -> None:
        def _fire():
            if msg.id not in self._timers:
                return  # 已收到 terminal result
            if attempt >= entry.retries:
                self.gateway.send_timeout(msg.id)
                del self._timers[msg.id]
                return
            self.gateway.route_to_executor(msg)
            self._set_timer(msg, entry, attempt + 1)

        handle = asyncio.get_event_loop().call_later(
            entry.timeout_ms / 1000, _fire)
        self._timers[msg.id] = handle

    def cancel(self, action_id: str) -> None:
        if action_id in self._timers:
            self._timers.pop(action_id).cancel()
```


---

## 9. Action Registry — RPA 动作注册表

### 9.1 Registry 数据模型

```typescript
interface ActionRegistryEntry {
    name: string;                        // dot-namespaced
    description: string;
    domain: string;                      // browser|desktop|api|erp|doc|human|context
    params: JSONSchema;
    idempotency: "required"|"optional"|"none";  // C3：只在此声明
    timeout_ms: number;
    retries: number;                     // 仅 idempotency=required 时有效
    risk: RiskLevel;                     // L0–L4
    requires_approval_at?: RiskLevel;
    audit_fields: string[];              // 必须记录的参数字段
    audit_mask_fields?: string[];        // 必须掩码的字段（密码等）
    expect?: string;                     // 期望后续事件名（AIP §4.2）
    allowed_principals?: string[];       // 空 = 所有已认证 principal
    executor_domain: string;             // 路由目标 Executor 类型
    deprecated?: boolean;
}
type RiskLevel = "L0"|"L1"|"L2"|"L3"|"L4"
```

### 9.2 风险分级定义

| 级别 | 语义 | 典型动作 | 默认策略 |
|---|---|---|---|
| **L0** | 只读，零副作用 | context.get, browser.extract | 自动放行 |
| **L1** | 低风险写入，副作用可撤销 | browser.click, browser.input | 自动放行，写审计 |
| **L2** | 中等风险，副作用持久但可回滚 | erp.order.approve（小额）, api.http.post | 自动放行，写审计，可告警 |
| **L3** | 高风险，难以回滚 | erp.invoice.post, email.send_external | 挂起，等待人工确认 |
| **L4** | 极高风险，不可逆 | bank.transfer, contract.sign | 强制双人审批 |

> L1 不代表"无需审计"——所有动作都写审计流，L 级别只影响自动放行阈值。

### 9.3 完整 Core Action Registry

```yaml
# ============================================================
# 上下文域（context.*）— 所有 Executor 支持
# ============================================================
context.get:
  executor_domain: any
  idempotency: required
  risk: L0
  timeout_ms: 5000
  retries: 3
  audit_fields: [ref, fields]

context.update:
  executor_domain: any
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 2
  audit_fields: [ref]

# ============================================================
# 浏览器域（browser.*）
# ============================================================
browser.navigate:
  idempotency: required
  risk: L0
  timeout_ms: 30000
  retries: 3
  audit_fields: [url]
  expect: "browser.page.loaded"

browser.click:
  idempotency: none        # 点击可能触发不可逆操作（表单提交等）
  risk: L1
  timeout_ms: 10000
  retries: 0
  audit_fields: [target]

browser.input:
  idempotency: required    # clear+fill 是幂等的
  risk: L1
  timeout_ms: 5000
  retries: 2
  audit_fields: [target]
  audit_mask_fields: [value]   # value 可能含密码

browser.select_option:
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 2
  audit_fields: [target, value]

browser.extract:
  idempotency: required
  risk: L0
  timeout_ms: 15000
  retries: 2

browser.wait_element:
  idempotency: required
  risk: L0
  timeout_ms: 30000
  retries: 1
  audit_fields: [selector]

browser.scroll:
  idempotency: optional
  risk: L0
  timeout_ms: 3000
  retries: 0

browser.upload_file:
  idempotency: none
  risk: L2
  timeout_ms: 120000
  retries: 0
  audit_fields: [target, filename]

browser.download_file:
  idempotency: required
  risk: L1
  timeout_ms: 180000
  retries: 1

browser.run_script:
  idempotency: none
  risk: L3                 # JS 执行高风险，禁止自动执行
  timeout_ms: 10000
  retries: 0
  requires_approval_at: L3
  audit_fields: [script_hash]  # 不记录完整脚本，只记录哈希

browser.take_screenshot:
  idempotency: required
  risk: L0
  timeout_ms: 5000
  retries: 2
  # 截图存入 ContextStore，ref 写入 result，不通过 AIP 传输原始字节（C6）

# ============================================================
# 桌面域（desktop.*）
# ============================================================
desktop.window.activate:
  idempotency: required
  risk: L0
  timeout_ms: 8000
  retries: 2
  audit_fields: [app_name, title]

desktop.window.close:
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 0
  audit_fields: [app_name]

desktop.element.click:
  idempotency: none
  risk: L1
  timeout_ms: 10000
  retries: 0
  audit_fields: [element_id, role]

desktop.keyboard.input:
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 1
  audit_fields: [target]
  audit_mask_fields: [text]

desktop.keyboard.shortcut:
  idempotency: none
  risk: L2
  timeout_ms: 3000
  retries: 0
  audit_fields: [keys]

desktop.file.copy:
  idempotency: required
  risk: L1
  timeout_ms: 60000
  retries: 2
  audit_fields: [source, dest]

desktop.file.move:
  idempotency: required
  risk: L2
  timeout_ms: 30000
  retries: 1
  audit_fields: [source, dest]

desktop.file.delete:
  idempotency: required
  risk: L3
  timeout_ms: 10000
  retries: 0
  requires_approval_at: L3
  audit_fields: [path]

desktop.process.launch:
  idempotency: none
  risk: L2
  timeout_ms: 30000
  retries: 0
  audit_fields: [executable, args_hash]

desktop.process.kill:
  idempotency: required
  risk: L2
  timeout_ms: 10000
  retries: 0
  audit_fields: [pid, process_name]

# ============================================================
# API / 集成域（api.* / email.*）
# ============================================================
api.http.get:
  idempotency: required
  risk: L0
  timeout_ms: 30000
  retries: 3
  audit_fields: [url]

api.http.post:
  idempotency: none        # POST 默认不幂等
  risk: L2
  timeout_ms: 30000
  retries: 0
  audit_fields: [url]

api.http.put:
  idempotency: required
  risk: L2
  timeout_ms: 30000
  retries: 2
  audit_fields: [url]

api.http.patch:
  idempotency: optional
  risk: L2
  timeout_ms: 30000
  retries: 0
  audit_fields: [url]

api.http.delete:
  idempotency: required
  risk: L3
  timeout_ms: 30000
  retries: 0
  requires_approval_at: L3
  audit_fields: [url]

email.send:
  idempotency: required    # 消息 ID 去重
  risk: L2
  timeout_ms: 30000
  retries: 1
  audit_fields: [to, subject, template]
  audit_mask_fields: [body]

email.send_external:
  idempotency: required
  risk: L3
  timeout_ms: 30000
  retries: 0
  requires_approval_at: L3
  audit_fields: [to, subject]

# ============================================================
# ERP 业务域（erp.*）— 推荐规范，由具体 Executor 覆盖
# ============================================================
erp.data.query:
  idempotency: required
  risk: L0
  timeout_ms: 30000
  retries: 3

erp.order.approve:
  idempotency: required
  risk: L2
  timeout_ms: 60000
  retries: 1
  audit_fields: [order_id, approver, amount_range]

erp.order.reject:
  idempotency: required
  risk: L2
  timeout_ms: 30000
  retries: 0
  audit_fields: [order_id, reason_code]

erp.invoice.post:
  idempotency: required
  risk: L3
  timeout_ms: 60000
  retries: 0
  requires_approval_at: L3
  audit_fields: [invoice_id, amount, vendor]

erp.payment.initiate:
  idempotency: required
  risk: L4
  timeout_ms: 60000
  retries: 0
  requires_approval_at: L4
  audit_fields: [amount, account_last4, beneficiary]

# ============================================================
# 文档域（doc.*）
# ============================================================
doc.extract_text:
  idempotency: required
  risk: L0
  timeout_ms: 60000
  retries: 2
  audit_fields: [document_ref, pages]

doc.extract_table:
  idempotency: required
  risk: L0
  timeout_ms: 60000
  retries: 2

doc.classify:
  idempotency: required
  risk: L0
  timeout_ms: 30000
  retries: 2

doc.fill_form:
  idempotency: required
  risk: L2
  timeout_ms: 60000
  retries: 1
  audit_fields: [document_ref, field_names]

doc.sign:
  idempotency: required
  risk: L4
  timeout_ms: 30000
  retries: 0
  requires_approval_at: L4
  audit_fields: [document_id, signer, signature_type]

doc.export:
  idempotency: required
  risk: L1
  timeout_ms: 60000
  retries: 2
  audit_fields: [document_ref, format, destination_ref]

# ============================================================
# 人工干预域（human.*）
# ============================================================
human.task.create:
  idempotency: required
  risk: L1              # 通知操作，不是业务操作本身
  timeout_ms: 5000
  retries: 2
  audit_fields: [task_type, assignee_role, context_ref]

human.task.cancel:
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 1
  audit_fields: [task_id, reason]

human.task.reassign:
  idempotency: required
  risk: L1
  timeout_ms: 5000
  retries: 1
  audit_fields: [task_id, from_assignee, to_assignee]
```

---

## 10. Session 与流程编排

### 10.1 Session 生命周期（精确状态机）

```
触发器（定时 / 事件 / 手动 / API）
    │
    ▼
INITIALIZING
    ├── 成功（所有 Executor 连接并 ready）→ RUNNING
    └── 失败（超时 / Executor 不可达）   → FAILED(init_failed) → END

RUNNING
    ├── human.task.create 执行成功   → SUSPENDED
    │       ├── human.task.completed → RUNNING（cursor+1 恢复）
    │       └── human.task.expired   → RUNNING（走 escalate 路径）
    │
    ├── Executor 连接断开            → RECOVERING
    │       ├── 重连 + hello + cursor → RUNNING（无状态丢失，AIP I3）
    │       └── 超时未重连            → FAILED(executor_lost)
    │
    ├── Decision Engine 不可达       → PAUSED
    │       └── 重连                  → RUNNING
    │
    ├── 所有步骤完成                 → COMPLETING → COMPLETED
    ├── action terminal failed       → FAILED(action_failed)
    └── 手动终止                     → CANCELLING → CANCELLED

FAILED / CANCELLED / COMPLETED 为终态，30 分钟后释放 Session 资源（可配置）。
```

### 10.2 流程定义（两种模式）

**模式 A：AI 驱动（Agentic Mode）**

适用于步骤不确定的非结构化任务：

```yaml
process:
  id: intelligent_invoice_processing
  mode: agentic              # Decision Engine 自主决策每一步
  trigger:
    type: event
    name: document.processing.started
    filter: "data.doc_type == 'invoice'"
  timeout_minutes: 30
  max_actions: 50            # 防止无限循环（必填）
  on_timeout: escalate_to_human
```

**模式 B：流程驱动（Process Mode）**

适用于步骤固定、合规要求严格的场景。注意：步骤中**不允许出现** `idempotency` / `risk`（C3），这些属性的唯一来源是 Action Registry：

```yaml
process:
  id: po_auto_approval
  mode: process
  version: "2.1"
  trigger:
    type: event
    name: erp.order.approval_requested
    filter: "data.risk_hint <= 'L2'"
  timeout_minutes: 60

  steps:
    - id: fetch_detail
      action: context.get
      params:
        ref: "{{ event.data.context }}"
        fields: ["order_id", "vendor_id", "amount", "requester_email"]
      on_failure: { goto: escalate }
      output_as: order

    - id: check_vendor
      action: erp.data.query
      params:
        entity: vendor
        id: "{{ steps.order.vendor_id }}"
        fields: ["status", "credit_rating"]
      on_failure: { goto: reject_order, reason: "vendor_query_failed" }
      output_as: vendor

    - id: ai_decision
      type: ai_decision       # 此节点由 Decision Engine 决策
      context: ["{{ steps.order }}", "{{ steps.vendor }}"]
      available_actions: [approve_order, reject_order, escalate]

    - id: approve_order
      condition: "{{ steps.ai_decision.outcome == 'approve_order' }}"
      action: erp.order.approve
      params:
        order_id: "{{ steps.order.order_id }}"
        approver: "apa_system"
      on_failure: { goto: escalate }

    - id: notify
      action: email.send
      params:
        to: "{{ steps.order.requester_email }}"
        template: "po_decision"
        context_ref: "{{ event.data.context }}"

  error_handlers:
    escalate:
      action: human.task.create
      params:
        task_type: exception
        assignee_role: procurement_manager
        priority: high
        context_ref: "{{ event.data.context }}"
    reject_order:
      action: erp.order.reject
      params:
        order_id: "{{ steps.order.order_id }}"
        reason_code: "{{ error.reason }}"
```

### 10.3 多 Bot 并发与游标管理

```
Session s_complex_001
    ├── Stream (browser_bot_01)   负责 Web 门户操作       seq: 1..N
    ├── Stream (desktop_bot_01)   负责桌面 ERP 客户端     seq: 1..M
    ├── Stream (api_bot_01)       负责 REST API 调用      seq: 1..K
    └── Stream (dsh_agent_001)    Decision Engine          seq: 1..J

路由规则：action 的目标 Executor 由 Registry.executor_domain 决定
任一 Bot 断线不影响其他 Bot（AIP I3）
断线 Bot 重连时携带 cursors，从正确位置恢复，无需重放
```

---

## 11. 错误处理与自愈

### 11.1 错误分类框架

```
AIP 协议错误（error 消息）          业务执行失败（result.failed）
─────────────────────────          ──────────────────────────────
INVALID_MESSAGE                    target_not_found
SEQ_OUT_OF_ORDER                   element_not_interactable
SESSION_EXPIRED                    page_not_loaded
UNAUTHORIZED                       api_timeout
AGENT_UNAVAILABLE                  permission_denied（业务层）
RPA_UNAVAILABLE                    validation_error
INTERNAL_ERROR                     erp_system_error
```

原则：协议错误不是业务失败，业务失败不是协议错误（AIP §4.7）。

### 11.2 三层自愈策略

**第一层：Executor 级自愈（毫秒级，不消耗 AIP seq）**

```python
class ResilientExecutor(AIPExecutor):
    async def _execute_with_local_retry(self, name: str, params: dict,
                                         max_attempts: int = 2) -> tuple[bool, dict]:
        """针对已知瞬时错误在 Executor 内部重试，不产生额外 AIP 消息"""
        for attempt in range(max_attempts + 1):
            try:
                return await self._execute_action(name, params)
            except ElementNotInteractable:
                if attempt < max_attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    await self._wait_for_stable_state()
                    continue
                return False, {"code": "element_not_interactable",
                               "retry": {"allowed": True, "after_ms": 1000}}
            except PageNotReady:
                if attempt < max_attempts:
                    await self.page.wait_for_load_state("networkidle")
                    continue
                return False, {"code": "page_not_ready",
                               "retry": {"allowed": True, "after_ms": 2000}}
```

**第二层：Gateway 级重试（秒级）**

基于 Registry `idempotency=required` + `retries` 由 RetryScheduler 驱动（§8.3）。

**第三层：Decision Engine 级自愈（分钟级）**

```python
async def on_terminal_result(self, result: AIPMessage) -> None:
    status = result.payload["status"]
    code = result.payload.get("code", "")
    retry_hint = result.payload.get("retry", {})

    match status:
        case "ok":
            await self._continue(result)
        case "rejected":
            await self._handle_policy_rejection(result)  # 不重试
        case "failed":
            strategy = self._decide_recovery(code, retry_hint)
            match strategy:
                case "retry_with_backoff":
                    await asyncio.sleep(retry_hint.get("after_ms", 1000) / 1000)
                    # Gateway RetryScheduler 已处理重发，此处只等待
                case "replan":
                    await self._replan(result)
                case "degrade":
                    await self._degrade(result)
                case "escalate":
                    await self.peer.send_action("human.task.create", {
                        "task_type": "exception",
                        "assignee_role": "rpa_operator",
                        "context_ref": self.current_context_ref,
                        "available_outcomes": ["retry", "skip", "abort"],
                    })
        case "timeout":
            await self._handle_timeout(result)

def _decide_recovery(self, code: str, retry_hint: dict) -> str:
    if retry_hint.get("allowed") and self._retry_budget > 0:
        return "retry_with_backoff"
    if code in DEGRADABLE_ERRORS:
        return "degrade"
    if code in REPLANABLE_ERRORS:
        return "replan"
    return "escalate"
```

### 11.3 熔断器（Circuit Breaker）

防止单一目标系统故障导致 Bot 不断重试并放大问题：

```python
class ExecutorCircuitBreaker:
    """
    CLOSED → OPEN（连续失败 ≥ 阈值）→ HALF_OPEN（等待超时后）→ CLOSED
    """
    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT_S = 60

    def before_action(self) -> None:
        if self.state == "OPEN":
            if time.time() - self.opened_at > self.RECOVERY_TIMEOUT_S:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError(f"Circuit OPEN for {self.target}")

    def on_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def on_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.FAILURE_THRESHOLD:
            self.state = "OPEN"
            self.opened_at = time.time()
```

---

## 12. 安全与审计

### 12.1 安全架构（纵深防御，四层）

```
第一层：传输安全
  · 生产强制 TLS 1.3
  · Bearer Token / OAuth 2.0 或 mTLS
  · source 绑定到认证 principal（AIP I9）

第二层：协议安全（Gateway 层）
  · source 与认证 principal 的绑定校验（每条消息）
  · Credential Pattern 扫描（AIP I10）：
      正则检测 password / api_key / Bearer / Authorization / secret
      Base64 encoded credential 检测
      发现即 reject + 告警（不记录 credential 内容）
  · Session 租户隔离（session 不可跨 tenant，ref 格式强制含 session_id）

第三层：凭据管理（Credential Vault）
  · Executor 启动时从 Vault 获取凭据（支持 HashiCorp Vault / 内置实现）
  · 凭据在 Executor 内存中，不序列化，不传输（C4）
  · 按 Session TTL 轮换，Executor 断线重连后重新获取
  · ref 格式 ctx_{session_id}_{name} 防止跨 Session 越权访问

第四层：执行安全（Executor 层）
  · Browser：域名白名单校验（allowed_domains 策略）
  · Desktop：进程白名单（禁止启动任意可执行文件）
  · API：请求头注入检测
  · 所有 Executor 支持 Dry Run 模式（沙盒验证）
```

### 12.2 Dry Run 模式

```python
class DryRunExecutor(AIPExecutor):
    """
    L1+ 风险动作模拟执行，返回虚构的 ok 结果。
    用途：流程测试、新员工培训、审计演练。
    """
    def __init__(self, *args, dry_run: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run = dry_run
        self.dry_run_log: list[dict] = []

    async def _execute_action(self, name: str, params: dict) -> tuple[bool, dict]:
        entry = self.registry.get(name)
        if self.dry_run and entry and entry.risk >= "L1":
            self.dry_run_log.append({"action": name, "params": params,
                                      "would_risk": entry.risk})
            return True, {"dry_run": True, "simulated": True}
        return await self._real_execute(name, params)
```

### 12.3 审计日志规范（Append-Only）

```json
{
  "audit_id": "aud_01J5X...",
  "schema_version": "1.0",
  "session": {
    "id": "s_process_001",
    "process_id": "po_auto_approval",
    "tenant_id": "corp_abc",
    "triggered_by": "event:erp.order.approval_requested"
  },
  "action": {
    "id": "act_00123",
    "name": "erp.order.approve",
    "source": "dsh_agent_001",
    "executor": "browser_bot_01",
    "in_reply_to_event": "evt_00098"
  },
  "security": {
    "verdict": "permitted",
    "risk_level": "L2",
    "policy_rules_applied": ["auto_approve_lt_100k", "vendor_in_whitelist"],
    "credential_scan": "clean"
  },
  "params_audit": {
    "order_id": "PO-5678",
    "approver": "apa_system"
  },
  "outcome": {
    "status": "ok",
    "duration_ms": 2340,
    "ts_start": 1786944500123,
    "ts_end": 1786944502463
  },
  "ai": {
    "model_used": "deepseek-v4-flash",
    "decision_level": "L1",
    "tokens_input": 312,
    "tokens_output": 48,
    "cost_usd": 0.000094,
    "think_mode": "non_think"
  }
}
```

### 12.4 合规覆盖

| 合规框架 | APA 对应机制 |
|---|---|
| GDPR 数据最小化 | CoD 字段级 ACL，事件 data 4KB 上限 |
| SOX 操作可追溯 | append-only 审计流，action+principal+outcome 完整记录 |
| ISO 27001 访问控制 | AIP I9 source 绑定，L3/L4 强制审批 |
| 内控四眼原则 | L4 强制双人审批（human.task 双签流程） |
| 紧急熔断 | Session 强制终止接口，in-flight action 标记 timeout |
| 审计日志完整性 | append-only 写入，支持 WORM 存储配置 |


---

## 13. 后端服务架构

### 13.1 服务职责划分

每个服务有明确的单一职责，便于开源社区分模块贡献：

```
apa-gateway/          Gateway 服务
  职责：AIP 消息路由、协议校验、策略执行、审计写入、Session 状态机
  语言：Python（与 AIP SDK 同语言，降低贡献门槛）
  依赖：Redis（cursor/session 热状态）

apa-process/          Process 管理服务
  职责：流程定义存储、版本管理、触发器匹配、步骤调度
  语言：Python
  依赖：PostgreSQL（流程定义/历史）

apa-scheduler/        调度服务
  职责：Cron/Event 触发、Bot Pool 管理、Session 创建
  语言：Python
  依赖：Redis（任务队列）、PostgreSQL（定时配置）

apa-audit/            审计服务
  职责：消费审计事件流、持久化、合规报告生成
  语言：Python
  依赖：Kafka/Redis Streams（事件源）、ClickHouse（分析存储）

apa-studio/           管理界面
  职责：流程监控、实时日志、Bot 状态、成本看板、策略配置
  语言：TypeScript / React
  依赖：apa-gateway SSE、apa-process REST、apa-audit REST

apa-vault/            凭据管理（可对接 HashiCorp Vault）
  职责：凭据加密存储、动态注入、轮换
  语言：Python
```

### 13.2 部署模式

**模式 A：单机（开发/测试/小规模）**

```yaml
# docker-compose.yml（单文件启动，面向新用户）
services:
  apa:
    image: apa/all-in-one:latest
    ports: ["8080:8080"]
    volumes: ["./data:/data", "./processes:/processes"]
    environment:
      APA_MODE: standalone
      APA_DECISION_ENGINE: rule    # 纯规则，无 LLM，最低门槛
      APA_STORAGE: sqlite          # 无需外部数据库
```

**模式 B：容器编排（生产）**

各服务独立部署，Gateway 水平扩展，通过内部 REST + Kafka 通信。

**模式 C：嵌入式（SDK，适合不想运行额外服务的场景）**

```python
# 在应用进程内嵌入 Gateway（AIP §2 明确支持 peer-to-peer）
from apa import EmbeddedGateway, BrowserExecutor, RuleBasedAgent

gateway = EmbeddedGateway(
    policy=PolicyConfig.from_file("policy.yaml"),
    registry=ActionRegistry.from_yaml("registries/browser.yaml"),
)
executor = BrowserExecutor(source="browser_01", gateway=gateway)
agent = RuleBasedAgent(gateway=gateway, rules=load_rules("rules.yaml"))
await asyncio.gather(executor.run(), agent.run())
```

---

## 14. 开发者体验与 SDK

10 分钟内跑通 hello world，30 分钟内写出第一个自定义 Executor——这是 APA 作为开源项目的核心体验目标。

### 14.1 仓库结构

```
apa/
├── README.md                      # 首屏：30 秒理解 APA 是什么 + 快速启动命令
├── QUICK_START.md                 # 10 分钟上手
├── CONTRIBUTING.md                # 模块边界、测试要求、PR 规范
├── SPEC_EXTENSIONS.md             # APA-Profile 规范（相对于 AIP SPEC.md 的扩展）
│
├── packages/
│   ├── apa-core/                  # 核心协议层（Python）
│   │   ├── gateway/               # APA-Gateway
│   │   ├── registry/              # Action Registry 引擎
│   │   ├── session/               # Session 状态机
│   │   ├── policy/                # 策略引擎
│   │   └── audit/                 # 审计事件流
│   │
│   ├── apa-executors/             # 标准执行器（Python）
│   │   ├── browser/               # BrowserExecutor（Playwright）
│   │   ├── desktop/               # DesktopExecutor（pywinauto / AT-SPI）
│   │   ├── api/                   # APIExecutor（httpx）
│   │   ├── document/              # DocumentExecutor
│   │   └── human-task/            # HumanTaskExecutor
│   │
│   ├── apa-sdk-python/            # 开发者 SDK（Python）
│   │   ├── executor_base.py       # Executor 基类（贡献新 Executor 的起点）
│   │   ├── semantic_adapter.py    # Schema-driven 适配器
│   │   ├── vision.py              # VisionAdapter（可插拔 VLM）
│   │   └── testing.py             # MockGateway / EventRecorder
│   │
│   ├── apa-sdk-typescript/        # 开发者 SDK（TypeScript）
│   │   ├── executor-base.ts
│   │   ├── decision-engine.ts     # Decision Engine 接口
│   │   └── dsh-plugin/            # dsh 接入插件
│   │
│   ├── apa-studio/                # 管理前端（React）
│   └── apa-process-engine/        # 流程编排引擎（Python）
│
├── registries/                    # 标准 Action Registry 定义（YAML）
│   ├── core.yaml                  # context.* / human.*
│   ├── browser.yaml
│   ├── desktop.yaml
│   ├── api.yaml
│   └── document.yaml
│
├── examples/
│   ├── hello-rpa/                 # 最小可运行示例（类比 AIP hello-rpa）
│   ├── web-form-automation/       # 网页表单填写
│   ├── po-approval/               # 采购审批（多 Executor 协同）
│   ├── invoice-processing/        # 发票处理（Document + AI）
│   └── custom-executor/           # 自定义 Executor 模板
│
├── conformance/                   # APA-Profile 合规测试套件
└── benchmarks/
    ├── vs_long_context/           # 与长上下文 Agent 对比（手动）
    └── executor_latency/          # 各 Executor 动作延迟分布（CI 自动）
```

### 14.2 Hello-RPA（最小可运行示例）

```python
# examples/hello-rpa/run.py
"""
APA Hello-RPA：在 10 分钟内体验 AI 驱动的 Web 自动化。
演示：打开搜索引擎 → 搜索关键词 → 提取第一条结果标题。
无需任何外部服务，使用内嵌 Gateway + 规则决策引擎（0 LLM 调用）。
"""
import asyncio
from apa import EmbeddedGateway, BrowserExecutor, RuleBasedAgent
from apa.registry import ActionRegistry
from apa.policy import PolicyConfig

RULES = [
    {
        "if": {"event": "browser.page.loaded", "url_contains": "search"},
        "then": {"action": "browser.extract",
                 "params": {"selectors": {"first_result": "h3:first-child"},
                            "output_context": "ctx_result"}}
    },
    {
        "if": {"action_result": "browser.extract", "status": "ok"},
        "then": {"action": "session.complete"}
    },
]

async def main():
    registry = ActionRegistry.from_yaml("../../registries/browser.yaml")
    gateway = EmbeddedGateway(
        session_id="s_hello_001",
        registry=registry,
        policy=PolicyConfig.permissive(),  # 演示：放行所有动作
    )
    executor = BrowserExecutor(source="browser_01",
                               session_id="s_hello_001", gateway=gateway)
    agent = RuleBasedAgent(gateway=gateway, rules=RULES)

    print("APA Hello-RPA 启动...")
    await asyncio.gather(
        executor.run(),
        agent.run(),
        executor.trigger_navigate("https://duckduckgo.com/?q=AIP+RPA+protocol"),
    )

    result = executor.context_store.get("ctx_result", ["first_result"],
                                         principal="demo")
    print(f"✓ 任务完成！首条结果：{result.get('first_result')}")
    print(f"  事件数：{gateway.stats.event_count}")
    print(f"  动作数：{gateway.stats.action_count}")
    print(f"  Token 消耗：0（纯规则模式）")

asyncio.run(main())
```

```bash
$ pip install apa-core apa-executors
$ python examples/hello-rpa/run.py

APA Hello-RPA 启动...
✓ 任务完成！首条结果：AIP — AI Interaction Protocol · GitHub
  事件数：3    动作数：2    Token 消耗：0（纯规则模式）
```

### 14.3 自定义 Executor 开发（30 分钟指南）

**Step 1：脚手架生成**

```bash
pip install apa-cli
apa create executor --name my-erp --domain erp
# 生成：
#   my-erp/executor.py       ← 只需实现两个方法
#   my-erp/schema.yaml       ← 语义适配器 Schema
#   my-erp/registry.yaml     ← Action 定义
#   my-erp/tests/            ← 预置测试框架
```

**Step 2：实现 `_execute_action` 和 `start_observation`**

```python
# my-erp/executor.py
class MyERPExecutor(AIPExecutor):
    def __init__(self, *args, erp_client, **kwargs):
        super().__init__(*args, **kwargs)
        self.erp = erp_client

    async def _execute_action(self, name: str, params: dict) -> tuple[bool, dict]:
        match name:
            case "erp.order.approve":
                order = await self.erp.get_order(params["order_id"])
                if order["status"] != "pending":
                    raise ExecutorPreconditionError("order_not_pending")
                result = await self.erp.approve(params["order_id"])
                return True, {"approval_id": result["id"]}

            case "context.get":
                data = self.context_store.get(params["ref"], params["fields"],
                                               principal=self.peer.source)
                return True, {"ref": params["ref"], "data": data}

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    async def start_observation(self) -> None:
        while True:
            for order in await self.erp.get_pending():
                ctx_ref = self.context_store.put(
                    f"ctx_order_{self.peer.session_id}_{order['id']}", order)
                self.peer.send_event("erp.order.approval_requested", {
                    "context": ctx_ref,
                    "available_actions": ["approve", "reject"],
                    "risk_hint": self._classify_risk(order),
                })
            await asyncio.sleep(30)
```

**Step 3：声明 Registry**

```yaml
# my-erp/registry.yaml
erp.order.approve:
  executor_domain: erp
  description: "批准 ERP 采购订单"
  params:
    order_id: { type: string, required: true }
    approver: { type: string }
  idempotency: required
  risk: L2
  timeout_ms: 60000
  retries: 1
  audit_fields: [order_id, approver]
```

**Step 4：测试（使用 MockGateway）**

```python
# my-erp/tests/test_executor.py
from apa.testing import MockGateway, EventRecorder

async def test_approve():
    gateway = MockGateway()
    recorder = EventRecorder(gateway)
    executor = MyERPExecutor(source="erp_01", session_id="s_test",
                              gateway=gateway,
                              erp_client=MockERP([{"id":"PO-001","status":"pending"}]))

    await gateway.inject_action("erp.order.approve", {"order_id": "PO-001"})

    assert recorder.results[-1] == ("ok", {"approval_id": "APR-001"})

    # 幂等性验证：同一 action_id 不重复执行
    await gateway.inject_action("erp.order.approve", {"order_id": "PO-001"},
                                 action_id="same-id")
    assert executor.erp.approve_call_count == 1
```

### 14.4 测试策略

```
单元测试（各 package 内部）
  目标覆盖率：> 85%
  框架：pytest（Python）/ Vitest（TypeScript）

集成测试（跨服务）
  AIP 官方 conformance 套件：21/21 通过
  APA-Profile conformance 套件：CoD 规则 / 事件 namespace 校验
  Gateway-Executor 端到端：使用 MockDecisionEngine

E2E 测试（真实浏览器）
  examples/ 下每个示例在 CI（GitHub Actions + Playwright）中可执行
  
性能基准（benchmarks/）
  executor_latency：每次 PR 自动运行，防止性能回归
  vs_long_context：手动运行，用于更新文档中的成本数字
```

---

## 15. 对标分析与差异化

### 15.1 功能覆盖对比

| 能力维度 | UiPath Enterprise | ShadowBot | MS Power Automate | **APA v1** |
|---|---|---|---|---|
| Web 自动化 | ✓ 成熟 | ✓ 成熟 | ✓ 成熟 | ✓（Playwright）|
| 桌面自动化 | ✓ 成熟 | ✓ 成熟 | ○ 有限 | ✓（pywinauto）|
| API 集成 | ✓ 成熟 | ✓ | ✓ Connector | ✓ |
| 文档理解 | ✓ Document Understanding | ○ | ○ AI Builder | ✓（LLM 驱动）|
| VLM 屏幕理解 | ○ 实验性 | ○ 有限 | ✗ | ✓（Executor 内置，C6 合规）|
| AI 决策集成 | ○ 黑盒调用 | ○ 规则+AI | ○ Copilot 生成 | ✓ 协议原生 |
| AI 成本控制 | ✗ 全量上下文 | ✗ | ✗ | ✓ CoD（实测验证中）|
| 断线精确恢复 | ○ 有限 | ○ | ○ | ✓ AIP cursor |
| 协议级幂等性 | ○ 应用层 | ○ | ✗ | ✓ I2 不变量 |
| Human-in-Loop | ✓ 成熟 | ○ | ✓ | ✓ Session 挂起原生支持 |
| 审计粒度 | 流程级 | 流程级 | 流程级 | 动作级 + AI 成本 |
| 开放 Action 扩展 | 官方市场 | 有限 | Connector | ✓ 开放 Registry（YAML）|
| 部署灵活性 | Cloud/On-prem | On-prem | Cloud-first | ✓ 嵌入式到集群 |
| 开源 | ✗ | ✗ | ✗ | ✓ MIT |
| AI 底座锁定 | 锁定 | 锁定 | 锁定 Azure AI | ✓ 模型无关（C1）|

图例：✓ 完整支持  ○ 部分支持  ✗ 不支持

### 15.2 核心差异化（诚实评估）

**差异化一：协议级可靠性（已实现，可验证）**

传统 RPA 的幂等性和错误恢复由开发者在应用层手写，每个流程各自实现，质量参差不齐。APA 通过 AIP 协议在基础层保证幂等性（I2）、断线不丢状态（I3）、精确游标恢复（§7.4）。继承 `AIPExecutor` 基类后，这些是"免费"的。

**差异化二：AI 成本可控（有机制，待实测验证）**

语义适配器 + AIP 事件 + CoD 的三层机制从设计上避免了将 DOM/截图全量投喂 LLM。实际节省幅度应以真实流程的基准测试替换理论估算。

**差异化三：开放生态**

三大商业 RPA 的 Action 扩展需要平台审核和账户绑定。APA 的 Action Registry 是 YAML 文件，任何人可以写 `my-sap-executor` 并开源，社区直接复用，无中间商。

**尚未实现的（v1 显式不含）：**

低代码流程设计器、Bot 池高可用自动切换、ERP Executor 完整功能、MCP/A2A 深度集成。这些在 README 中明确列出，不在功能表中虚标。

---

## 16. 开源项目规划

### 16.1 MVP 定义（v0.1 发布标准）

**必须完成才能发布：**

- [ ] `examples/hello-rpa` 在 Linux/macOS 一键 `python run.py` 跑通
- [ ] BrowserExecutor 基础动作（navigate/click/input/extract）通过测试
- [ ] APA-Gateway 通过 AIP conformance 套件（21/21）
- [ ] 纯规则 Decision Engine 可用（无 LLM 依赖）
- [ ] APA-Profile conformance 套件（≥ 10 个测试用例覆盖 CoD 规则）
- [ ] 自定义 Executor 文档（15 分钟能写出 hello 级 Executor）
- [ ] APA-Studio 最小版（仅 Session 日志查看）

**v0.1 显式不包含（README 中明确声明）：**

Desktop Executor、LLM 决策引擎、流程编排（只有 Agentic Mode）、Credential Vault、多租户。

### 16.2 版本规划

| 版本 | 周期 | 核心目标 | 验收场景 |
|---|---|---|---|
| **v0.1** | M0–M2 | 协议层 + Browser Executor + 规则引擎 | Web 表单填写端到端 |
| **v0.2** | M3–M4 | Document Executor + LLM 接口 + Human-in-Loop + Session 持久化 | 发票扫描→提取→写 ERP |
| **v0.3** | M5–M6 | Desktop + API Executor + Process Mode + APA-Studio v1 | 采购审批多 Bot 协同 |
| **v1.0** | M7–M9 | Policy Engine 完整 + Vault + Analytics + 多租户 + ERP 参考实现 | 企业内部生产部署 |

### 16.3 贡献优先级

| 贡献类型 | 优先级 | 说明 |
|---|---|---|
| 新 Executor 的 ElementSchema | 高 | 直接扩展可自动化的目标系统，社区影响力最大 |
| 新 Action Registry 条目（高质量） | 高 | 质量比数量重要，需附带测试 |
| 语言版本 SDK（Java/Go） | 中 | 等 SDK 接口稳定（v0.3+）再做 |
| dsh 以外的 Decision Engine 适配 | 中 | 需 TypeScript SDK 稳定后 |
| APA-Studio 功能扩展 | 低（v1 前） | 核心协议稳定前 UI 变化频繁 |
| 低代码流程设计器 | 低（v1 前） | 依赖 Process Engine API 稳定 |

---

## 17. 附录 A：完整消息序列示例

### 示例：采购订单审批（规则引擎 + CoD，含完整游标）

```
执行器流 (browser_bot_01)       Gateway          决策流 (rule_agent_001)
─────────────────────────       ───────          ──────────────────────

# ── 建立连接 ─────────────────────────────────────────────────────────
→ hello { session:"s_po_001", cursors:{} }
                                                 ← hello { session:"s_po_001", cursors:{} }

# ── 规则引擎预设：进入时导航到待审批列表 ─────────────────────────────
                                ◄── seq:1 action browser.navigate
                                         { url:"erp.corp.com/po/pending",
                                           wait_for:"networkidle" }
seq:1 result accepted →
seq:2 result ok       →         cursor:{bot:2}

# ── 页面加载，语义适配器匹配 pending_orders pattern ──────────────────
# [ContextStore.put("ctx_page_s_po_001_001", {url, count:3, ...})]
seq:3 event browser.page.loaded →   cursor:{bot:3}
      { url:"erp.corp.com/po/pending",
        context:"ctx_page_s_po_001_001" }

# 规则：page.loaded + url=pending → click first-order-row
                                ◄── seq:2 action browser.click
                                         { target:"first-order-row" }
seq:4 result accepted →
seq:5 result ok       →         cursor:{bot:5}

# ── 订单详情加载，语义适配器匹配 approval_dialog ─────────────────────
# [ContextStore.put("ctx_order_s_po_001_PO5678", {订单全量数据})]
seq:6 event erp.order.approval_requested →  cursor:{bot:6}
      { context:"ctx_order_s_po_001_PO5678",    ← 引用，不是对象（C5）
        available_actions:["approve","reject"],
        risk_hint:"L2" }

# 规则引擎：amount 不在事件 data 中，需要 CoD fetch
                                ◄── seq:3 action context.get
                                         { ref:"ctx_order_s_po_001_PO5678",
                                           fields:["amount","vendor_credit"] }
# [Gateway: L0 风险，直接放行]
seq:7 result accepted →
seq:8 result ok       →
      { ref:"ctx_order_s_po_001_PO5678",
        data:{ amount:45000, vendor_credit:"A" } }

# 规则命中：amount < 100000 且 vendor_credit = "A" → approve
                                ◄── seq:4 action erp.order.approve
                                         { order_id:"PO-5678",
                                           approver:"apa_system" }
# [Gateway 校验链：Registry ✓ / Schema ✓ / 权限 ✓ / Risk:L2 Policy:auto ✓
#                 Credential scan:clean ✓ / 审计写入 / 路由 Executor]

seq:9  result accepted →
seq:10 result running  →        [RetryScheduler: 重置 timeout timer]
seq:11 result ok       →        cursor:{bot:11}
       { erp_result:"approved",
         approval_id:"APR-001" }
# [Gateway: action 状态 → SUCCESS / RetryScheduler: cancel timer / 审计更新]

# ── 发送通知邮件 ──────────────────────────────────────────────────────
                                ◄── seq:5 action email.send
                                         { to:"zhang.san@corp.com",
                                           template:"po_approved",
                                           context_ref:"ctx_order_s_po_001_PO5678" }
seq:12 result accepted →
seq:13 result ok       →

# ── 订单状态变更事件 → 规则引擎判断：所有步骤完成 ─────────────────────
seq:14 event erp.order.status_changed →  cursor:{bot:14}
       { order_id:"PO-5678", from:"pending", to:"approved" }

                                ◄── seq:6 action session.complete
                                         { outcome:"success" }
# [Gateway: Session → COMPLETING → COMPLETED]

# ── 最终状态 ──────────────────────────────────────────────────────────
# Cursors: { browser_bot_01:14, rule_agent_001:6 }
# 任意节点在此之前断线，均可从对应 cursor 精确恢复（AIP I3）

# ── 成本统计 ──────────────────────────────────────────────────────────
# 规则模式：Token = 0
# 若规则未命中升级到 V4-Flash：~350 input + 60 output ≈ $0.00012（估算）
# AIP 消息总数：20（event:5 / action:6 / result:9）
```

---

## 18. 附录 B：已知问题与设计权衡

透明记录已知问题是获得社区信任的重要方式。

### B.1 已知技术问题

**问题 1：语义适配器的冷启动门槛**

新目标应用需要人工编写 ElementSchema，对 RPA 新用户有门槛。计划：提供"Schema 录制模式"（Recording Mode），Bot 在 headful 模式下运行时自动记录触发动作的元素，生成 Schema 草稿供人工审核。

**问题 2：WebSocket 高频事件流瓶颈**

AIP v0.1 只支持 WebSocket 绑定，在 > 1000 events/sec 场景下单连接可能成为瓶颈。HTTP Binding（AIP §9.7）在 AIP Roadmap 中，APA 可提前实现 HTTP profile 作为补充。

**问题 3：跨 Session 上下文引用越权**

若 Gateway 隔离不严格，理论上可猜测 ref 访问他 Session 数据。缓解：强制 ref 格式 `ctx_{session_id}_{name}`，Gateway 在 `context.get` 时校验 ref 前缀与当前 session_id 匹配。

**问题 4：VLM Fallback 延迟不稳定**

当 Accessibility API 失败时，VLM 分析（本地）延迟可能达到 2–5 秒，显著影响用户体验。建议在 Desktop Executor 的 Health Check 阶段预热 VLM，并为 VLM fallback 设置 5 秒硬超时（§5.4）。

**问题 5：Polling vs Webhook 的延迟差异**

当前 `start_observation` 使用轮询（30 秒间隔），对于支持 Webhook 的目标系统，延迟差距明显。Webhook 模式需要 Executor 暴露可访问端口，在企业防火墙下不总可行。两种模式并存，由具体 Executor 选择。

### B.2 设计权衡

**流程定义 YAML vs 图形化编辑器**

选择 YAML 的原因：可进入 Git 版本控制，易于 Code Review，适合 DevOps 工作流。图形化编辑器作为 Phase 2/3 的可选层，而不是必须层。代价：初期上手曲线略陡。

**Python 优先 vs 多语言**

选择 Python 的原因：AIP 官方 SDK 有 Python 实现，Playwright/pywinauto RPA 工具链最成熟，AI/ML 生态也在 Python。代价：TypeScript-first 的用户需要等 SDK v2（M6 后）。

**Embedded Gateway vs Standalone Gateway**

提供两种部署模式：嵌入式适合开发/轻量部署，Standalone 是生产推荐但增加运维复杂度。

**事件轮询 vs Webhook**

两种模式并存，不强制。Webhook 优先（低延迟），轮询兜底（防火墙友好）。

### B.3 开放讨论题（欢迎社区参与）

1. **与 Browser Use / Computer Use 的关系**：BrowserUse 等工具将 VLM 驱动操作作为第一公民，APA VisionAdapter 与这类工具的最佳集成方式？
2. **Session 持久化粒度**：逐条持久化引入延迟，批量持久化有丢消息风险。最佳粒度？
3. **多租户 Bot Pool 调度**：Bot 资源紧张时高优先级流程如何抢占？Scheduler 是否需要优先级队列？
4. **ERP Executor 的测试环境**：SAP/Oracle 测试环境门槛极高，如何构建 Mock ERP 供社区贡献者使用？

---

*APA v0.2 设计文档 · 2026-08-20*

*协议基础：AIP Kernel v0.1 — MIT License (emVisible/AIP)*  
*参考实现：DeepSeek Harness v0.1 — MIT License (deepseek-ai/deepseek-harness)*  
*本文档：Apache 2.0（允许衍生，要求署名）*

---

> **致未来的贡献者**：这份文档是开放的，不是最终稿。
> 如果你发现任何技术错误、设计缺陷或更好的方案，
> 请直接开 Issue 或提 PR 修改本文档。
> 协议永远比文档重要，实测数字永远比理论估算可信。

