# 贡献指南（APA POC）

## 模块边界

| 包 | 职责 | 禁止 |
|---|---|---|
| `apa-core` | 协议层：Gateway 校验链、Registry、Policy、Session 状态机、审计、规则引擎 | 不做 I/O；不 import 执行器 |
| `apa-sdk-python` | Executor 基类与横切能力（自愈/防抖/DryRun/语义适配/测试工具） | 不含具体目标系统的知识 |
| `apa-executors` | 具体执行器（Playwright/httpx） | 不做决策 |

依赖方向：`apa-executors → apa-sdk-python → apa-core → aip`。反向 import 一律拒绝。

## 架构约束（违反即拒绝 PR）

设计文档 §2.2 的约束在此重申，评审时逐条对照：

- C3 idempotency/risk 只出现在 Registry YAML
- C4 凭据不进 payload（Gateway 会扫描并 reject）
- C5 大对象传引用（ref 格式 `ctx_{session}_{name}`）
- C6 截图/VLM 输出不进入 AIP 协议
- C7 Decision Engine 无状态
- 事件命名 `{domain}.{entity}.{state_change}` 完成时态，禁止命令式

## 测试要求

```bash
python -m pytest tests/          # 全绿
python conformance/run.py        # 20/20
```

新增 Action Registry 条目必须附带：
1. YAML 条目（含 params schema、risk、timeout、retries、audit_fields）
2. Schema 校验测试（合法/非法参数各一）
3. 若 risk ≥ L2：说明默认策略行为是否符合 §9.2

新增语义适配器模式必须附带 MockPage 测试（不依赖真实浏览器）。

## 提交规范

- 分支：`poc` 为 POC 主线；特性分支 `poc/<topic>`
- 提交信息：`<area>: <summary>`，如 `gateway: enforce C3 contraband check`
- 每个逻辑变更一个 commit，保持 bisect 友好
