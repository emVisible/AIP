# APA CHANGELOG

## v1.0+ Phase 11 — 常驻服务 + cordis 实机联调

- **ServeApp 常驻栈**：Studio(HTTP) + Scheduler(tick 循环) + 本地会话执行线程池
  单进程运行；`apa serve` 子命令与 `webui.sh --serve` 接线；
  scheduler.yaml 批量加载 cron/event 任务（到点跑 data/processes 流程）
- **HTTP 外部事件入口**：`POST /api/events` → Scheduler.dispatch_event
  （serve 模式自动接线；未配置返回 501）
- **cordis 实机联调**：真实 cordis 4.0.0-rc.8 容器挂载 @apa/dsh-plugin ——
  Service 提供 llm → inject 解析等待 → apply 注入 → 决策闭环实测通过
  （tests/test_phase11.py::TestCordisRuntime）；修复插件双重包装导致
  结果回执静默丢弃的缺陷（模块注册统一由 ProcessRunner 收口）

## v1.0+ Phase 10 — dsh 底座接入 + 低代码起步

- **dsh 插件运行时打通**：pnpm 安装 cordis 4.0.0-rc.8（卡点原为版本标签）；
  完整 tsc 编译通过；apply() 经 dist 产物对 Python 网关完成真实决策闭环
  （事件→llm.complete→解析→sendAction→执行器点击），pytest 锁定为回归
- agent.ts 加固：绑定层帧（hello-ack/pong/gateway 回执）不进入决策流；
  peer.handle 异常防御
- Studio 低代码起步：/api/registry/actions 动作目录 API（表单数据源）
- pnpm 全面替代 npm（CI/scripts/docs）；DeepSeek .env 接口（config.py +
  .env.example）；WS 后台调度循环修复无 clock 时超时/TTL 失效缺陷；
  Studio Bearer 认证

poc 分支演进记录（设计文档 §16.2 版本规划 + 补全阶段）。

## v1.0+ Phase 8 — 控制平面补全

- **apa-scheduler**：`CronExpr` 标准 5 字段 cron（*/n、范围、列表，纯 stdlib）；
  `Scheduler` 支持 Cron 触发（同一自然分钟去重）与 Event 订阅（data 条件过滤）
- **ProcessRunner / run_process**：流程启动器泛化 —— 任意 process.yaml +
  复合执行器规格 + `seed_contexts` CoD 预置 + 自动 session.complete 收尾
  （escalated 挂起时不收尾）；po-approval 验收场景迁移复用
- **统一 CLI**：`apa studio|analytics|tasks|latency`（console script）
- 测试：cron 边界（范围/步进/非法输入/星期语义）、调度去重与事件过滤、
  launcher 端到端（订单批准 + 通知落 ERP）

## v1.0+ Phase 7 — 生产加固

- **TLS**：`WsGatewayServer(ssl_context=...)` wss://；`generate_dev_certs()`
- **令牌准入**：hello 帧校验 `hello_token`
- **多会话池**：单服务多 Session（hello.session 路由），连接表/出站泵按会话隔离
- **SqliteJournal**：stdlib sqlite3 后端；`open_journal` 按扩展名选择；
  recover/studio/analytics/human_loop 统一读取层兼容
- **延迟基准**：内嵌回路 p50≈0.03ms / ≈3600 ops/s（§14.4）

## v1.0+ HITL 交互闭环

- Studio 网页审批面板（批准/驳回按钮 → POST resolve → 会话恢复）
- `examples/human-approval`：大额发票人工复核演示（approve/reject 双分支）
- **修复** 拦截型动作 seq 空洞：GapTolerantReceiver（嵌入式对端）
- **修复** StudioServer journal glob 急展开 → 惰性求值

## v1.0+ Phase 6 — 跨语言联调

- Node(@aip/protocol) 决策端 ↔ Python WsGatewayServer 真实套接字 E2E
  （锁定 DE-1/D1/D4/params.target 线级契约）
- GitHub Actions CI：python 矩阵 + TS SDK + 跨语言三 job

## v1.0+ Phase 5 — 感知与生态

- VisionAdapter 插槽（OpenAI-compatible VLM，bounds 剥离于协议前 — C6）
- SchemaRecorder 录制模式（§B.1）：动作→元素→schema.yaml 草稿
- HashiCorpVaultBackend（KV v2 HTTP）

## v1.0 — 生产加固核心

- Credential Vault（scrypt+HMAC-CTR 加密、TTL、Executor 注入层 — C4）
- Policy Engine 完整（通配规则/主体黑名单）+ 速率限制
- 多租户隔离（journal 标记/hello 校验/Studio·Analytics 过滤）
- Analytics（成功率/耗时 p50·p95）+ MockERP 参考实现

## v0.3 — Process Mode 与多 Bot

- ProcessEngine（§10.2 模式 B）：AST 白名单条件求值、ai_decision 插槽、
  on_failure/goto、max_actions 守卫；po-approval 双分支验收场景
- DesktopExecutor（Osascript/Mock 后端）、API 轮询观察
- WS 多 Bot 域路由（§10.3）；APA-Studio v1
- 修复：Gateway 自有回执缺 seq 导致对端静默丢弃

## v0.2 — LLM 决策与远程接入

- OpenAI-compatible LLMClient + 防御性 parse_decision；Zero-LLM Cascade
- WebSocket 独立网关；Human-in-the-Loop 拦截/恢复；SessionJournal 持久化
- DocumentExecutor + invoice-processing 验收场景；dsh 插件参考实现（TS）

## v0.1 — 协议层与浏览器执行器

- APAGateway 校验链（I9/S1-S5/C4 扫描/风险策略/重试调度）
- Action Registry（YAML，C3 唯一来源）；APAContextStore（CoD 三规则）
- BrowserExecutor（Playwright + MockPage 双模）；规则决策引擎（0 Token）
- hello-rpa 示例 + APA-Profile 合规套件 20 用例