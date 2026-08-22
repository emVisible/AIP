# hello-rpa — APA 最小可运行示例

在 10 分钟内体验 AI 驱动的 Web 自动化（§14.2）。
演示：打开采购订单待办页 → 语义适配器识别审批对话框 → 规则引擎按金额决策
→ 点击批准 → 提取结果 → 会话完成。**无需任何 LLM，0 Token。**

## 运行

```bash
python run.py --mock    # 无浏览器（CI/无 Playwright 环境）
python run.py           # 真实 Playwright headless Chromium
```

期望输出：

```
== APA hello-rpa: Agentic Process Automation 最小示例 ==
→ 导航: file://.../test_page/index.html

决策引擎步骤：
  · rule[approve_small_order]: browser.click {'target': 'approve-btn-1'}
  · rule[read_result]: browser.extract {...}
  · rule[complete]: session.complete {'outcome': 'success', ...}

提取结果: {'result': '已批准订单 PO-5678'}
事件数: 4  动作数: 2  Token 消耗: 0（纯规则模式）
Session 状态: COMPLETED  审计记录: 7

RESULT: OK — 已审批订单 PO-5678
```

## 消息流（E→D→A→R）

```
executor --event browser.page.loaded-----------> gateway --> agent (规则未命中)
executor --event erp.order.approval_requested--> gateway --> agent (amount<100000 → 命中)
agent    --action browser.click 批准----------> gateway --> executor
executor --result accepted/ok-------------------> gateway --> agent
executor --event erp.order.approval_requested'-> gateway --> agent (once 规则不重复触发)
agent    --action browser.extract 结果---------> gateway --> executor
executor --result ok {output_context}----------> gateway --> agent
agent    --action session.complete-------------> gateway (Session → COMPLETED)
```

要点：
- 订单数据留在 Executor 的 ContextStore，事件只带 `context` 引用与已解析字段（C5）
- 页面状态签名未变化时不重复发事件（防事件风暴，配合 §6.3 Coalescer）
- `once: true` 规则整个 Session 只执行一次（防重复触发）
- 所有动作经 Gateway 校验链：Registry / Schema / 凭据扫描 / 风险策略 / 审计

## 文件

| 文件 | 角色 |
|------|------|
| `run.py` | 装配 EmbeddedGateway + BrowserExecutor + 规则引擎并驱动 |
| `schema.yaml` | 语义适配器 ElementSchema：页面模式 → 业务事件（§6.2） |
| `rules.yaml` | 决策规则：金额阈值 → 点击批准 → 读取结果 → 完成 |
| `test_page/index.html` | 本地演示页（data-apa-id 标注的目标应用） |

试试把 rules.yaml 的阈值改为 `{ lt: 40000 }` —— 规则不再命中，
点击不会发生，Session 保持 RUNNING：这就是"AI 不持有执行权、
规则说了算"的最小展示。
