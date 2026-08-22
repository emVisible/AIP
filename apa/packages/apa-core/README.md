# apa-core

APA 协议层核心（设计文档 §8/§9/§10/§12）：

- `gateway.py` — APA-Gateway：消息路由、校验链、重试调度、Session 状态机
- `registry.py` — Action Registry 引擎（YAML 加载、JSONSchema 校验）
- `policy.py` — 风险分级策略引擎（L0–L4）
- `context.py` — APAContextStore（CoD-1/2，ref 格式强制）
- `session.py` — Session 状态机（§10.1）
- `audit.py` — append-only 审计日志（§12.3）
- `rules.py` — 规则决策引擎（§7.2 L0，0 Token）
- `embedded.py` — EmbeddedGateway（§13.2 模式 C）

依赖：`aip`（AIP Python SDK）、`pyyaml`、`jsonschema`。