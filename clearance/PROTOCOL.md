# PROTOCOL — AIP 思想 → Clearance 实现对照表

本文件是唯一的协议概念文档：只记录“思想落在哪段代码”，不复述协议原文。
原文已删（见 git 历史），行为以代码和测试为准。

## 循环：E → D → A → R

| AIP 概念 | Clearance 实现 |
|---|---|
| Event（已发生的语义事实） | `POST /api/review/submit` → `ReviewItem{kind,title,body,meta}`（`store.py`），`data ≤ 4KB` |
| Decision（引擎内决策，非消息） | `cascade()`（`engines.py`）：`rules→laya:sidecar→jev→heuristic`，首个 Decision 胜出；Decision Engine 是真插槽（C1），不是写死的 Laya 调用 |
| Action（具名能力调用） | 7 动作注册表 `REGISTRY`（`gateway.py`）：`review.approve/reject/defer`、`human.task.create`、`context.get`、`notify.send`、`session.complete` |
| Result（客观结果） | `state: approved/rejected/pending` + `audit.jsonl` 只追加审计流（`store.py` + `gateway.audit_log`） |

## 不变量 → 代码位置

| # | 不变量 | 实现 |
|---|---|---|
| I1/I2 | 动作去重：同一 id 不二次执行 | `store.submit/resolve` 单文件状态机；`test_store.py::test_roundtrip`（重复 resolve 抛错） |
| I4/I5 | event 只观察、action 只命令 | `models.py` 类型分离；`questions.py` 只产决策输入 |
| I6 | terminal 后不回迁 | `resolve` 仅 `pending → approved/rejected`，否则 `ValueError` |
| I9 | 来源绑定 | server 只绑 `127.0.0.1`；`actor` 字段写审计 |
| I10/C4 | 凭据禁入 payload | `_CRED_RE` 扫描（`gateway.py`）；`test_gateway.py::test_credential_blocked` |
| C3 | 幂等/risk 只来自 Registry | `REGISTRY` 唯一声明处；消息体禁带 |
| CoD | 大对象传引用、按需取 | 事件体 `>4KB` 拒绝（`test_oversize_blocked`）；`context.get` 为 L0 动作保留 |
| 门控 | 低置信转人工 | `gateway.route(action, conf, threshold)`；`eval/sweep.py` 定阈值，原则 auto_err=0 |

## conformance 取舍

旧 `conformance/` 行为用例已删；可产品化的 3 条转为单元测试：
未知动作拒绝、凭据拦截、低置信转人工（`test_gateway.py`），
存储往返与重复解决（`test_store.py`），HTTP 全链路（`test_server.py`）。
传输层（WS 绑定/seq/cursor/resume）本产品不需要——单体文件存储无此故障域，
故不实现、不测试、不写文档。
