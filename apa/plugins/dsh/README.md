# @apa/dsh-plugin — dsh 决策引擎插件（参考实现）

把 [DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness)
作为 APA 的 Decision Engine 接入（设计文档 §7.3，C1：决策引擎可替换插槽）。
经 AIP WebSocket 绑定连接 APA-Gateway：事件进 → LLM 决策 → 动作出。

```
┌─────────────┐  AIP over WS   ┌──────────────┐  in-process  ┌──────────────────┐
│ APA Gateway │◄──────────────►│ @apa/dsh-    │◄────────────►│ dsh llm service  │
│ (Python)    │  event/action  │ plugin       │   inject     │ (DeepSeek V4 …)  │
└─────────────┘                └──────────────┘              └──────────────────┘
```

## 目录

| 文件 | 角色 |
|------|------|
| `src/agent.ts` | 协议核心（仅依赖 `@aip/protocol`）：hello 握手、事件→LLM→动作、DE-1/2/3/5 契约、context_get 关联 |
| `src/index.ts` | cordis 胶水：适配 dsh `llm` 服务 → `LlmLike`，挂载/卸载 agent |

## Python 侧启动网关

```python
import asyncio
from apa_core.registry import load_registries
from apa_core.policy import PolicyConfig
from apa_core.gateway import APAGateway
from apa_core.ws_gateway import WsGatewayServer

async def main():
    gw = APAGateway(
        "s_po_001",
        registry=load_registries("apa/registries/core.yaml",
                                 "apa/registries/browser.yaml"),
        policy=PolicyConfig(),
        identities={"executor": "browser_01", "agent": "dsh_agent_001"},
    )
    server = WsGatewayServer(gw, port=8765)
    port = await server.start()
    print(f"APA gateway on ws://127.0.0.1:{port}")
    await server.serve_forever()

asyncio.run(main())
```

## dsh 侧挂载

```bash
cd /path/to/deepseek-harness
pnpm install                       # cordis 等依赖
pnpm --filter @apa/dsh-plugin build   # 或在插件目录 pnpm build
```

在 composition 的 cordis.yml 中加入：

```yaml
- id: apa-decision
  name: '@apa/dsh-plugin'
  config:
    gatewayUrl: ws://127.0.0.1:8765
    sessionId: s_po_001
    source: dsh_agent_001          # 必须与网关 identities.agent 一致（I9）
    allowedActions:
      - context.get
      - browser.navigate
      - browser.click
      - erp.order.approve
      - human.task.create
    thinkEvents: [erp.order.approval_requested]   # 这些事件走 L2 深度推理
```

## 行为契约（设计文档 §7.1）

- **DE-1** 只消费 terminal result；accepted/running 不触发决策
- **DE-2** 需要更多字段时发标准 `context.get` action（CoD），不缓存 Session 状态（C7）
- **DE-3** action 只带 name/target/params —— idempotency/risk 由 Registry 声明，
  Gateway 校验链兜底（P2：AI 永远不持有最终执行权）
- **DE-5** LLM 输出 uncertain 或越权动作名 → 自动转 `human.task.create`，
  Session SUSPENDED，等待人工

## ✅ 运行时验证（v0.5 已完成）

`apply()` 全链路已在 CI 级测试中实测通过（`tests/test_phase10.py::TestDshGlueRuntime`）：
编译产物 dist/index.js → apply(ctx) → WsClientTransport 连接 Python 网关 →
事件到达 → llm.complete({messages}) 被调用 → 防御性解析散文包裹的 JSON 决策 →
allowedActions 校验 → sendAction 执行器真实点击。类型层面：完整 tsc 编译
通过（cordis 4.0.0-rc.8 实装；其 d.ts 存在 TS2694 发布缺陷，胶水层改用
结构化最小上下文绕开——见 src/index.ts 顶部注释）。

## 跨语言联调验证（已通过）

`tests/e2e_client.mjs` 使用与插件**完全相同**的协议核心
（`@aip/protocol` AIPPeer + WsClientTransport，含 `sendRaw` 绑定层帧），
对 Python WsGatewayServer 做真实套接字端到端验证：

```
[node] connected
[node] hello ack ok (cursors={"bot_01":1})
[node] pong received (D4)
[node] event: browser.page.loaded seq=1
[node] action sent: browser.click target=approve-btn
[node] progress: accepted          ← DE-1：非终态不触发决策
[node] terminal ok — cross-language loop closed
```

运行：`pytest apa/tests/test_phase6.py`（需 node ≥ 18；
CI 的 cross-language job 已覆盖）。该测试同时锁定了两个线级契约：
per-stream seq 跨语言一致、params.target 与 Registry schema 对齐。

## 类型检查

```bash
# 协议核心（无需 cordis，本地可验证）
npx tsc -p tsconfig.check.json
# 完整编译（需 pnpm install 提供 cordis 类型；离线环境不可用时
# 以 e2e_client.mjs 运行时验证替代——上节已通过）
pnpm build
```

## 已知边界（诚实声明）

- `adapt()` 基于 cordis/dsh 公开接口形态编写；dsh llm 服务面演进时单点调整。
- 多 Session 并行需为每个 session 启动独立 agent 实例（POC 单连接单会话）。
- cordis 4.0 尚为 rc 版：类型经结构化绕开（不影响运行时），待正式版后可回迁命名导入。