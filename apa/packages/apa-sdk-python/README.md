# apa-sdk-python

开发者 SDK（设计文档 §14）。贡献新 Executor 的起点：

- `executor_base.py` — `AIPExecutor` 基类（协议层职责基类处理，子类只实现业务层）
- `resilient.py` — 本地重试 + 熔断器（§11.2 第一层 / §11.3）
- `dry_run.py` — Dry Run 模式（§12.2）
- `coalescer.py` — 事件防抖（§6.3）
- `semantic_adapter.py` — Schema-Driven 语义适配器（§6.2）
- `testing.py` — MockGateway / EventRecorder / MockBrowser（§14.3）

依赖：`apa-core`、`aip`、`pyyaml`。