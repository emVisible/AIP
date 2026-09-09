# APA × Harness 融合设计（H1–H6 路线）

> 信源：`harness-deepseek`（DeepSeek Harness，MIT）与 `harness-codex`
> （OpenAI Codex，Apache-2.0）。本文件是融合实施的权威依据：
> 每项资产给出源路径、窃取形态、APA 落点与验收标准。
> 原则：**偷，不抄**——代码可移植则移植；算法照实现；数据文件直接用；
> 纯概念只留一行参考。禁止重造轮子。

---

## §0 已锁决策（2026-08 记录）

| 决策 | 内容 |
|---|---|
| D-1 | 首攻 **H1 底座**（会话溯源 + jobs 生命周期 + spill），后续按序推进 |
| D-2 | Codex Rust 资产**仅取设计与数据文件**（协议分类学、.sbpl、JSONL schema），不引入 cargo 组件/sidecar |
| D-3 | 本轮交付=本文档；实施自下一轮 H1 起 |
| D-4(v1.1) | Cordis **字面引入冻结**（本体仅 ~2.7k 行 TS，成本在语义迁移而非体量）；三支柱语义待触发条件满足后经原生迷你内核落地（宪法 §八）。触发：①第二常驻表面立项 ②Pack 热插需求 ③手写清理补丁再现≥2次 |
| D-5 | dsh workflow（模型写 JS 跑 vm）**不采纳**——与 ProcessEngine 确定性哲学冲突；仅偷其取消/并发限额/force-terminate 设计 |

## §1 许可义务

| 信源 | 许可 | 义务 |
|---|---|---|
| harness-deepseek | MIT | 保留版权声明于衍生文件头 |
| harness-codex | Apache-2.0 | 引入代码/数据文件的目录放置 NOTICE 副本并标注修改；专利授权随文件传递 |

两者均与 APA 的 MIT 兼容。落地规则：凡移植文件头部加
`// Ported from <repo> (<path>) — <license>`；`.sbpl` 等数据文件同目录附
`NOTICE.apa.md`。

## §2 信源盘点

### 2.1 dsh（TS monorepo，pnpm，全 ESM strict TS）
「一切皆插件」基于 vendored Cordis（`harness-deepseek/vendor/cordis`）。
进程拓扑：单 Node 进程 `dsh --profile web|headless` 启动插件树；
webserver 托管静态 dist + HTTP RPC（apiproxy BFF）+ WS upgrade 事件下行。

### 2.2 Codex（Rust workspace + TS/Python SDK）
引擎主循环在 `codex-rs/core`（54k 行，不碰）；事件经
`app-server-protocol/src/protocol/event_mapping.rs` 映射为
ServerNotification 推送；接口形态为 JSON-RPC over stdio / unix socket /
websocket（无 REST）。消息类别：
thread(start/complete/error) · turn · item(agent_message / reasoning /
command_execution / file_change / mcp_tool_call / todo_list / error) ·
approval 请求(elicit)。

## §3 窃取清单总表

| # | 资产 | 源路径 | 形态 | 评级 | APA 缺口 | 阶段 |
|---|---|---|---|---|---|---|
| 1 | 事件溯源会话（模型可见⟺已记录 + JSONL append-only + 投影查询） | `harness-deepseek/packages/core/session/src/index.ts`、`packages/session/*persistence*`、codex `codex-rs/rollout/` | Python 移植 | A-/B+ | Workbench 对话为内存缓存刷新即失；运行审计无回放 | H1 |
| 2 | jobs 生命周期协议（owner 围栏/幂等取消/done 结算） | `harness-deepseek/packages/jobs/jobs/src/types.ts` | Python 移植 | A | 后台任务生命周期缺失 | H1 |
| 3 | compaction + spill（摘要压缩节点 / 大输出落盘返引用） | `harness-deepseek/packages/compaction/compaction/src/index.ts`、`packages/spill/spill/src/{index,types}.ts` | Python 中间件 | A/B | cascade_llm 长上下文膨胀；extract_table 大结果整段入上下文 | H1 |
| 4 | plan-mode 审批态机（计划态注入 + exit_plan_mode 用户出口） | `harness-deepseek/packages/plan/plan-mode/src/index.ts` | 模式翻译 | A | 意图环确认门升级为一等状态机 | H2 |
| 5 | 协议三态分类学（request/response/notification + item 粒度 + elicitation + ts 类型单源导出 ts-rs） | codex `codex-rs/app-server-protocol/src/protocol/common.rs`；transport 仅 91 行见 `app-server-transport/src/transport/{stdio,unix_socket,websocket}.rs` | 设计照搬 + 类型生成 | A | 三端通道散装（REST/SSE/IPC 各行其是，双前缀类 bug 的结构性温床） | H3 |
| 6 | macOS Seatbelt 沙箱策略与 spawn 封装 | codex `codex-rs/sandboxing/src/seatbelt.rs` + 同目录 `.sbpl`×4（base/network/restricted_read_only_platform_defaults/preferences） | 数据文件直接用 + wrapper 移植 | A- | `code.python` 为裸 subprocess（L3 无隔离） | H4 |
| 7 | MCP 双向互通（registry→MCP server；外部 MCP 工具→动作自动注册） | codex `codex-rs/mcp-server/` 思路；dsh mcp-client 设计 | Python 实现（官方 sdk） | B/A | 186 动作无生态出口；外部能力接入靠手写 executor | H5 |
| 8 | client 连接层（ws 下行事件流 + HTTP RPC 上行 + apiproxy BFF + zustand runtime） | `harness-deepseek/packages/client/connection/src/`、`packages/client/runtime`、apiproxy | TS 近直接搬 | A | 前端数据层散装 fetch/SSE | H6 |
| 9 | schedule 定频任务（持久日志驱动） | `harness-deepseek/packages/schedule` | Python 移植 | A | 定时触发器缺口 | H6+ |
| 参考 | agent-graph-store（479 行零依赖父子线程拓扑 trait） | codex `codex-rs/agent-graph-store/` | 摘取 | A | 子流程编排拓扑（远期） | - |
| 参考 | apply-patch 纯算法 parser/seek_sequence | codex `codex-rs/apply-patch/src/` | 摘取 | B+ | 流程补丁式编辑（远期） | - |

## §4 H1 详细设计（首发，可实施粒度）

### 4.1 会话事件溯源（对应资产 #1）

**边界声明**：APA 已有 process journal（运行审计流）。本节新增的是
**对话会话流（chat session log）**——Workbench 与未来任何 LLM 决策点的
统一持久层。二者并存，互不替代。

**数据模型**（偷 dsh session 不变量 + codex rollout 形态）：
- 存储：append-only JSONL，一 session 一文件，
  `apa/data/sessions/<session_id>.jsonl`
- 事件 envelope：`{seq, ts, kind, payload}`，seq 单调递增（写前读尾）
- kind 初版集合：`message.user` / `message.assistant` /
  `draft.created` / `draft.approved` / `tool.invoked` / `tool.result` /
  `error` —— 与 AIP Event/Result 语义对齐，后续 H3 并轨
- **不变量**：任何进入 LLM 上下文的内容必须已存在一条事件
  （模型可见 ⟺ 已记录）。实现方式：LLM 调用前先落事件，再渲染 prompt
- **投影（projection）**：从 JSONL 全量推导对话视图（纯函数，
  events → messages[]），不做增量索引；查询接口
  `list_sessions() / read_session(id) / project(id)`
- 参照实现：dsh `core/session` 的 durable/live 事件二分与
  codex `rollout` 的 append-only + 反向扫描

**APA 落点**：新建 `apa/packages/apa-core/apa_core/sessions.py`；
Workbench 的模块级 `_msgCache` 删除改为读写该层；
SSE 复用现有 journal 推送通道模式新增 `/api/sessions/{id}/stream`。

**验收标准**：
1. 发起对话 → 刷新页面 → 消息完整恢复（含草稿审批状态）
2. 手工篡改 JSONL 中间行 → 投影检测 seq 断裂并告警
3. `project()` 输出与逐条渲染一致（纯函数幂等）

### 4.2 jobs 生命周期（对应资产 #2）

**移植清单**（自 dsh `jobs/jobs/src/types.ts`，语义级翻译为 Python dataclass）：
- JobRecord：id / kind / owner_session / status(running|done|cancelled) /
  created_at / settled_at / result_ref
- 操作约束：cancel 幂等（重复 cancel 返回同一终态）；非 owner 取消 → 拒绝
  （owner 围栏）；done 时结算钩子（settlement）恰好执行一次

**接缝**：现有 `ServeApp.load_jobs`（定时流程调度，占用 `/api/jobs`）
保持不动；新层命名为 **bgjobs**（`/api/bgjobs`，运行时后台任务注册表，
命名冲突记录：与既有定时调度 CRUD 撞名故独立路径），先服务三类内部
后台任务：spy 会话、browser_pick 会话、recorder 会话——它们当前是
各自为政的单例布尔，统一收编为可列举/可取消的 Job。

**APA 落点**：`apa_core/jobs.py` + `/api/jobs` 只读列举端点。

**验收标准**：
1. 同一 job 连续 cancel ×3 → 单终态、无异常
2. 会话 A 创建的 job，会话 B cancel → 拒绝且原状态不变
3. done 结算钩子执行次数 == 1

### 4.3 spill 中间件（对应资产 #3）

**行为**：工具/动作结果体积超阈值（默认 32KB 序列化文本）时：
原文落盘 `apa/data/spills/<ref>.json`，返回引用对象
`{spill_ref, path, bytes, preview(≤2KB), truncated:true}` 进上下文。
LLM 决策链路凭 spill_ref 可按需回读（Context-on-Demand 的物理实现）。

**集成点**：ProcessEngine 动作结果出口统一过一道
`maybe_spill(action_name, result)`；首期白名单：`browser.extract_table`、
`file.read_csv`、`doc.extract_text`、`ocr.extract`。

**参照**：dsh `spill/types.ts` 的引用契约 + output-retention 截断策略。

**H2 落地修订（已闭环）**：引擎出口接管采用**参数化 opt-in**——步骤
params 声明 `spill: true`（四个白名单动作 schema 已加该开关）才触发
落盘替换，避免破坏 `{{steps.<id>.rows}}` 模板消费语义；配套内置动作
`context.spill_read`（不经 gateway、不消耗动作预算）作为回读通道；
试运行响应层默认对白名单大结果 spill。白名单修正：OCR 项实际动作名
为 `ocr.extract`（初稿误写 ocr.recognize）。

**验收标准**：
1. 10 万行 extract_table → 上下文中只有引用对象，preview 完好
2. spill 文件损坏 → 回读端报明确错误而非静默空值
3. 小结果（<阈值）路径零变化（快照测试）

### H1 明确不做

- 多设备同步、SQLite 索引（JSONL 规模足够，索引是 codex rollout 为海量
  会话做的优化，暂不需要）
- compaction 自动摘要（依赖 LLM 预算策略，放 H2 后评估；本期只做 spill）

## §5 H2–H6 简版

| 阶段 | 目标 | 来源 | 验收一句话 |
|---|---|---|---|
| H2 计划态确认门 | 意图编译产物进入 plan 态，exit 需用户显式批准，全程事件化 | dsh plan-mode | 未批准的草稿不可能被执行入口触达 |
| H3 Studio 协议 v1 ✅（三期） | request/response/notification 三态 + item 粒度运行事件 + elicitation；TS 类型由 Python 单源生成 | codex app-server-protocol（含 91 行 transport 分层示范） | 三端共用一份类型定义，旧 REST/SSE 经适配层过渡。落地：`apa_core/studio_protocol.py` 单源 + `studio_codegen.py`→`frontend/src/shared/studioProtocol.ts`（漂移门禁）+ `/api/studio/rpc` 统一通道（错误语义五态）；Workbench 为首个消费方；notification SSE 已接线；run.step 经引擎观察者真实发射；process.save/test、yaml.*、processes.list 已迁入（templates.list 已随模板库删除）；剩余长尾 REST 渐进迁移 |
| H4 沙箱 code.python ✅ | `.sbpl` 四份策略文件直接落地 + sandbox-exec spawn wrapper；L3 默认沙箱、白名单逃逸需审批 | codex sandboxing | 沙箱内进程无网络/越界写，策略文件可独立审计。落地：`apa_executors/sandbox.py` + `profiles/code_python_default.sbpl`（单工作区模板替代 codex 参数机），`code.python` 默认沙箱、params.sandbox 可关、结果带 sandboxed 标注 |
| H5 MCP 互通 ✅ | registry 包装为 MCP server；外部 MCP 工具经发现协议注册为新动作（risk 标注继承） | codex mcp-server 思路 + dsh mcp-client | 双向落地：出口=`mcp_server.py` 零依赖 stdio 服务（187 工具，risk≥L2 门禁）；反向=`mcp_client.py`+`McpBridgeExecutor`——env `APA_MCP_SERVERS` 声明外部服务器，两稳定动作 `mcp.tools_list`/`mcp.tool_call` 消费任意外部工具（狗粮闭环测试：自家 server 作外部端） |
| H7 AI 配置子系统 ✅（后端+RPC；UI 下轮） | 分层设置树 defaults<user<project<env<override，双写用户层；LLM 适配缝+token meter+retry；auth_spec 走 vault/env 引用（C4） | codex config profiles + dsh settings(redact)/llm-retry/token-meter | 五层优先级矩阵/redact 门禁/双写回读/profiles 热切换 全部测试锁定；旧 env 兼容并标记 owned 拒写 |
| H6 前端连接层 ✅（首批） | ws/SSE 下行 + RPC 上行统一数据层 | dsh client/connection + runtime | 设计器核心读写（sessions/process.save·test/yaml.*/processes.list）已全覆盖 studioRpc；剩余长尾渐进迁移 |

## §6 非目标与边界

- 不引入 Cordis / 不重构 Pack 体系（Pack 是动作层插件，Cordis 是进程级
  插件，层级不同，互不相欠）
- 不采纳 dsh workflow（模型写 JS）、codex code-mode（V8/gRPC 过载）、
  agent-identity（HTTP 强耦合）
- closed shadow DOM、跨域 iframe 等浏览器硬边界延续拾取轮结论
- Rust 二进制 sidecar 一律不引入（D-2）

## §7 附录：源路径速查（已逐一验证存在）

```
dsh 会话        harness-deepseek/packages/core/session/src/index.ts
dsp 持久化      harness-deepseek/packages/session/*persistence*
jobs 契约       harness-deepseek/packages/jobs/jobs/src/types.ts
compaction      harness-deepseek/packages/compaction/compaction/src/index.ts
spill           harness-deepseek/packages/spill/spill/src/{index,types}.ts
plan-mode       harness-deepseek/packages/plan/plan-mode/src/index.ts
client 连接     harness-deepseek/packages/client/connection/src/
schedule        harness-deepseek/packages/schedule
codex 协议      harness-codex/codex-rs/app-server-protocol/src/protocol/common.rs
codex transport harness-codex/codex-rs/app-server-transport/src/transport/
codex 沙箱      harness-codex/codex-rs/sandboxing/src/seatbelt.rs (+ .sbpl×4)
APA 沙箱落地    apa/packages/apa-executors/apa_executors/{sandbox.py,profiles/}
codex rollout   harness-codex/codex-rs/rollout/
codex mcp-server harness-codex/codex-rs/mcp-server/
codex py-sdk    harness-codex/sdk/python/
graph-store     harness-codex/codex-rs/agent-graph-store/
apply-patch     harness-codex/codex-rs/apply-patch/src/
```

> 维护约定：H1 实施时若发现源设计与本文冲突，以实际源码为准并回改本文
> （决策记录追加 §0），保持文档与实现的单一真相方向：**仓库 > 文档 > 记忆**。
