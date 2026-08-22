# APA Quick Start（10 分钟）

## 0. 环境准备

```bash
cd apa
python3 -m venv .venv
source .venv/bin/activate

# AIP SDK + APA 三个包 + 依赖
pip install -e ../sdk/python \
             -e packages/apa-core \
             -e packages/apa-sdk-python \
             -e packages/apa-executors
pip install pyyaml jsonschema pytest httpx

# 浏览器自动化（可选，hello-rpa 真实模式需要）
pip install playwright && python -m playwright install chromium
```

## 1. 跑通 hello-rpa（2 分钟）

```bash
python examples/hello-rpa/run.py --mock    # 无浏览器，确定性演示
# 或真实浏览器：
python examples/hello-rpa/run.py
```

期望输出：

```
决策引擎步骤：
  · rule[approve_small_order]: browser.click {'target': 'approve-btn-1'}
  · rule[read_result]: browser.extract {...}
  · rule[complete]: session.complete {'outcome': 'success', ...}
RESULT: OK — 已审批订单 PO-5678   Token 消耗: 0（纯规则模式）
```

发生了什么（§3.2 关键数据流）：

```
BrowserExecutor 导航待办页
  → 语义适配器识别"审批对话框"（schema.yaml 声明，非硬编码）
  → event erp.order.approval_requested {context: ctx_…, amount: 45000.0}
  → 规则引擎：amount < 100000 → action browser.click 批准
  → 提取结果文本 → session.complete → Session COMPLETED
```

注意：订单全量数据留在 Executor 的 ContextStore 里，事件只带引用与已解析字段（C5）。

## 2. 跑合规套件（1 分钟）

```bash
python conformance/run.py     # APA-Profile：CoD / C3 / C4 / I9 / 风险策略 …
python -m pytest tests/       # 单元 + 端到端
```

## 3. 写一个最小自定义 Executor（5 分钟）

```python
# my_bot.py
from aip import AIPPeer
from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import ActionRegistry, RegistryEntry
from apa_core.rules import RuleBasedAgent, RuleEngine
from apa_sdk import AIPExecutor

class ClockExecutor(AIPExecutor):
    """每次被询问时报告当前 tick。"""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.ticks = 0

    def _execute_action(self, name, params):
        if name == "clock.tick":
            self.ticks += 1
            return True, {"tick": self.ticks}
        return False, {"code": "action_not_supported_by_executor"}

    def start_observation(self):
        self.emit("bot.session.started", {"executor_ids": ["clock_01"]})

# 1) 注册动作（idempotency/risk 只在这里声明 — C3）
registry = ActionRegistry.from_dict({
    "clock.tick": dict(executor_domain="any", idempotency="optional",
                       risk="L0", timeout_ms=1000),
})

# 2) 组装内嵌 Gateway
gw = EmbeddedGateway("s_my_001", registry=registry,
                     policy=PolicyConfig(),
                     identities={"executor": "clock_01", "agent": "rule_01"})
executor = ClockExecutor("clock_01", "s_my_001")
agent = RuleBasedAgent(AIPPeer("rule_01", "s_my_001"), [
    {"if": {"event": "bot.session.started"},
     "then": {"action": "clock.tick", "params": {}}},
])
gw.attach_executor(executor, "clock_01")
gw.attach_agent(agent, "rule_01")
gw.run()
executor.start_observation()
print("ticks:", executor.ticks)
```

```bash
python my_bot.py    # → ticks: 1
```

要点：
- 子类只写业务层；幂等守卫、accepted 先回、错误分类、context.* 由基类提供
- 事件名必须形如 `domain.entity.state_change` 且 domain 在白名单中（§4.1）
- 事件 data ≤ 4KB（CoD-1），大对象放 ContextStore 传引用

## 4. 下一步

- 读 [`../APA_Design_Document_v2.md`](../APA_Design_Document_v2.md) 了解完整设计
- 读 [`../../SPEC.md`](../SPEC.md) 了解 AIP 协议内核
- 为新目标系统写 ElementSchema（参考 `examples/hello-rpa/schema.yaml`）
