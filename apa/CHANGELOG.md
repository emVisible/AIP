# Changelog — APA (Agentic Process Automation)

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### AFL P2 · 存量迁移＋模板库删除（Occam）
- `tests/fixtures_dsl/` 新增 `data-scrape-report.afl`（等价测试锁定）；
  `apa/templates/*.yaml` 删除（内容已迁 goldens）
- 设计器 `TemplateLibrary`＋`importTemplate` 删除（整图覆盖导入下线；
  模板概念并入 golden 示例库）；后端 `GET /api/templates`＋
  `templates.list` RPC＋`list_templates_payload`＋`yaml` import 一并删除
- `tests/test_dsl.py` 24 passed；typecheck＋build ✓

### Harness 融合 H7 · AI 配置子系统（后端一期）
- **`settings.py` 分层设置树**：defaults < user(~/.apa) < project(apa.config.yaml)
  < env(兼容映射标记 owned) < active_profile；deep_merge 嵌套合并；
  原子写回用户层；坏项目层 YAML 容忍降级
- **结构化脱敏（C4 对齐）**：树中无 api_key 字段——仅 auth_spec 引用
  `{"vault"| "env"}`，运行时经 VaultManager 解析；schema 递归拒绝未知键，
  开放字典（auth_spec/profiles）显式豁免
- **LLM 缝升级**：chat_metered 带 usage 解析 + 429/5xx/传输错误指数退避；
  env_owned 路径写回拒绝（提示改环境变量）；rpc `settings.get/update`、
  `usage.summary`；codegen 再生成 TS 类型
- 新增 pytest ×14（分层矩阵/脱敏/双写/profiles/开放字典豁免），全量
  **517 passed**；Studio 设置页 UI 与 vault 写入粘合为 H7b 下轮

### 收尾轮 · H6 渐进迁移 + 审批引出闭环
- **RPC 方法扩容**：processes.list / templates.list / yaml.from_form /
  yaml.to_form（api 层编排，模板载荷 REST/RPC 共用）；ValueError 统一映射
  invalid_params
- **前端切换**：设计器 YAML 双向同步、保存前投影、流程列表刷新、模板库
  全部改走 studioRpc（长尾 REST 仅剩只读/低频面，渐进迁移）
- **approval.elicit 发射闭环**：计划态门拒绝时容器同步推送审批引出——
  UI ticker `⏸ 待审批` 数据源打通；测试锁定
- 架构宪法 §七「脚本编辑安全」从事故候选转正；融合文档 H3 三期/H6
  首批标记更新

### Harness 融合 H7b · Studio 设置页（UI 双写）
- **`useSettings` hook + 四张设置卡**：AI 模型（provider/model/base_url/
  auth_spec 引用类型+名称/temperature）、审批策略（风险级选择）、沙箱
  （Seatbelt/MCP 高风险开关）、外部 MCP 服务器列表编辑器——全部经
  `settings.update` 热应用并原子写回用户层；env-owned 字段自动只读并
  标注 🔒 来源；密钥仅编辑引用规格，明文永不经过 UI（C4）
- **跨测试 env 泄漏修复**：ServeApp 经 .env 向全局 environ 注入
  APA_LLM_MODEL 等遗留变量且不清理，破坏下游设置类测试 owned 语义——
  conftest 新增全局 autouse 守卫（快照/恢复 LEGACY_ENV_MAP）
- 新增 pytest ×3（settings rpc 往返/双写/owned 拒写映射、usage 零态、
  elicit 发射），全量 **520 passed, 0 失败**

### Harness 融合 H5 二期 · 外部 MCP 反向接入
- **`mcp_client.py` 零依赖 stdio 客户端**：握手/list/call，select 超时
  防御坏服务器；`McpPool` 命名客户端池（env `APA_MCP_SERVERS` JSON 配置）
- **`McpBridgeExecutor`**（域 mcp.）：两稳定动作——`mcp.tools_list`
  （枚举外部工具）/ `mcp.tool_call`（调用取回文本结果，risk=L2 默认审批级）；
  serve 装配接入（env 未配置静默跳过）
- **狗粮闭环测试**：以自家 mcp-serve 作外部端，经桥列出 187+ 工具并
  真实调用 string__upper 取回数据；registry +2 动作（189），全量
  **501 passed, 0 失败**

### Harness 融合 H5 · MCP 出口（一期）
- **`mcp_server.py` 零依赖 stdio 服务**：Action Registry 暴露为标准
  MCP server——initialize / tools/list / tools/call / ping 协议子集，
  任意 MCP 客户端可发现并调用全部动作（工具名点号→双下划线消毒，
  description 携带原始名+中文标签+风险级，inputSchema 透传 registry）
- **执行走直调模式**：registry 驱动域能力令牌路由（string.* 等数据族
  正确映射 data 执行器），返回真实数据而非仅状态；risk≥L2 默认拒绝并
  返回审批指引（env/flag 显式放行）
- CLI 新增 `mcp-serve` 子命令；新增 pytest ×7（含真实 stdio 子进程
  initialize→tools/list→tools/call 端到端），全量 **496 passed**

### Harness 融合 H3 三期 · run.step 真实发射 + H6 首批迁移
- **引擎观察者**：ProcessEngine 新增 step_observer（DI，域层不知传输层），
  主执行路径 ok/failed 均触发；launcher.run_process /
  StudioServer.test_run_process 全链透传；试运行端点以 svc.notify 发射
  `run.step`（session=sandbox）——SSE `/api/studio/events` 有了真实生产者
- **H6 首批迁移**：TestRunPanel 试运行与设计器保存切换至 Studio RPC
  （process.test / process.save，计划态凭证随行）
- 测试：conftest 类级补丁 StudioServer（保留直播语义）；新增
  test_testrun_emits_live_run_steps 端到端验证总线可订阅
- **事故与恢复记录**：一次脚本切片误删 api.py 中段（FastAPI 实例化至
  录制器段），经 HEAD 骨架重放 + 会话补丁清单确定性重建；DesignerPage
  因脚本写错目标文件被覆盖，按终态架构权威重写。恢复后全量
  502 passed、typecheck/build 通过、bundle 断言命中。教训固化为宪法
  候选条款：多段脚本编辑前必须先落盘快照再操作

### H3 二期 · notification 下行 + 宪法合规压缩
- **NotificationHub**（CoreServices）：进程内通知总线——丢最旧不阻塞引擎、
  订阅退订对称；`svc.notify(method,payload)` 唯一发布入口
- **`GET /api/studio/events`** SSE 下行：心跳防断连、可选 sid 过滤、断连
  finally 退订；TestClient 不逐块冲刷无限流的工具边界已记录，真实流经
  curl 手动验收
- **rpc_table 迁入 CoreServices**：方法注册表归容器，api 层只剩分发+错误映射
- **宪法合规压缩**：spy 权限预检下沉 `spy.ensure_accessibility()`；
  spill 后处理下沉 `spill.spill_test_response()`；端点函数体回到 ≤10 行
- 前端 `useStudioEvents` hook + DesignerPage 状态栏事件 ticker；
  新增 pytest ×6，全量 **489 passed**

### 根基加固 v1（架构宪法确立）
- 新增 `docs/architecture-principles.md`：六纲——分层铁律（transport 禁业务
  逻辑）/状态所有权（可变单例必须挂容器）/路径真相源（paths.py，env
  APA_DATA_DIR 重定向）/错误语义（RPC 五态权威）/演进纪律（只加不改/
  生成物禁手改）/测试基座（conftest 共享夹具）
- **api.py 消解 god-module**：63 处散装单例/nonlocal 全部收编
  `core_services.CoreServices` 容器（jobs/sessions/spills 具体实例 +
  spy/picker/recorder/scrape 惰性槽位），create_app 增 services 注入参数
  （向后兼容），nonlocal 归零；transport 层职责纯化第一步
- `paths.py` 数据路径单一真相源；spill 默认存储接入；
  CoreServices 防御式收敛路径字符串参数
- 新增 `tests/conftest.py` 共享夹具（core_services/stub_serve/client），
  H2 测试迁移至夹具

### Harness 融合 H3 · Studio 协议 v1（一期）
- **类型单源** `apa_core/studio_protocol.py`（pydantic）：三态信封
  （RpcRequest/RpcResponse + notification 载荷：item 粒度 run.step /
  run.outcome / approval.elicit）——分类学对齐 Codex app-server-protocol
- **代码生成管线** `studio_codegen.py`：pydantic→JSON Schema→TS，
  产物 `frontend/src/shared/studioProtocol.ts`（GENERATED 头）；
  pytest 漂移门禁拦手改
- **统一 RPC 通道** `/api/studio/rpc`：方法注册表分发
  （session.* / bgjobs.* 五方法），错误语义五态
  （method_not_found/invalid_params/not_found/conflict/internal_error），
  会话篡改映射 conflict；具体异常先于 KeyError 泛化分支
- **首个消费方**：Workbench 对话读写迁移至 `studio.ts` 类型化客户端
  （studioRpc），旧 REST 并存过渡；新增 pytest ×5，全量 483 passed

### Harness 融合 H4 · Seatbelt 沙箱（code.python）
- `code.python` 从裸 subprocess 升级为 **macOS Seatbelt 沙箱执行**：
  策略文件直接取自 Codex `.sbpl` 裁剪（Apache-2.0，NOTICE 同目录）——
  读放开、写限工作区/系统临时目录、网络默认拒绝
- `apa_executors/sandbox.py`：命令装配 + 内容寻址 profile 缓存；
  darwin 默认开启、params.sandbox 可显式关闭、结果带 sandboxed 标注；
  registry schema 同步 +1 开关
- 集成测试验证真实沙箱边界：工作区内写成功 / 工作区外写被拒且文件不存在；
  非 darwin 平台显式跳过

### Harness 融合 H2 · 计划态确认门 + spill 闭环
- **计划态服务端强制**：/api/processes/save|test 接受 session_id+draft_id
  溯源凭证，会话日志中无 draft.approved 事件即 409——未批准草稿在服务端
  不可能触达执行入口；手工流程（无凭证）不受限。前端链路：Workbench
  批准落凭证 → 设计器保存/试运行自动携带（TestRunPanel 透传）
- **spill 引擎闭环**：内置动作 `context.spill_read`（不经 gateway、不消耗
  动作预算）作为回读通道；引擎出口参数化接管——白名单四动作 schema 新增
  `spill` 开关，声明即超阈值落盘替换；registry +1 动作（187）
- 融合文档 §4.3 偏差记录闭环；新增 pytest ×6（批准门 e2e ×4 +
  spill 引擎级 ×2）

### Harness 融合启动（设计）
- 新增 `docs/harness-fusion.md`：APA × DeepSeek Harness / Codex 融合设计——
  9 项资产窃取清单（源路径逐一验证）、H1–H6 分期路线（会话溯源底座 →
  计划态确认门 → Studio 协议 v1 → Seatbelt 沙箱 → MCP 互通 → 前端连接层）、
  Apache-2.0/MIT 许可义务；已锁决策：Rust 仅取设计与数据文件、Cordis 不引入

### H1 底座落地（docs/harness-fusion.md §4 实施）
- **会话事件溯源** `apa_core/sessions.py`：append-only JSONL + seq 连续性
  篡改检测（末行撕裂容忍）+ 纯函数投影（消息/草稿状态机）；
  「模型可见⟺已记录」不变量；`/api/sessions` 三端点；
  Workbench 重写接入——刷新恢复对话、草稿审批持久化、删除内存缓存
- **后台任务生命周期** `apa_core/jobs.py`：移植 dsh jobs 协议——owner
  围栏/幂等取消/done 恰好一次结算；spy/browser_pick/recorder 三服务
  收编为可列举可取消的 bgjobs（`/api/bgjobs*`，与既有定时调度
  `/api/jobs` 命名冲突已记录于融合文档）
- **spill 大结果落盘** `apa_core/spill.py`：32KB 阈值 + 白名单四动作 +
  引用契约 `{spill_ref,bytes,preview}` + 损坏显式报错；首期接入
  试运行响应层（引擎出口全量接管待 spill 回读动作设计，偏差已记录）
- 新增 pytest ×18（sessions 8 / jobs 5 / spill 5）；全量 467 passed

设计器 UI 重构（对齐影刀三栏 IDE 布局）+ 动作目录全量中文化 + 桌面拾取闭环。

### 拾取闭环（第二轮）
- **根治 API 双前缀缺陷（桌面拾取 Not Found 的统一根因）**：client.ts
  api()/post() 自动拼 /api 前缀而大量调用点传入已带前缀路径，实际请求
  /api/api/* 全线 404——桌面拾取 start/capture、试运行、保存、YAML 双向
  同步、模板库、录制器、抓取向导、引擎状态 chip 均曾中招；入口处路径
  归一化一处修复整类问题，并删除 DesignerPage 本地重复 post 助手
- **联通可观测化（网页拾取）**：面板轮询失败不再静默——连续 3 次失败
  显示「后端不可达」横幅；显示最近事件版本号与时间心跳；引导文案注明
  打包版应用重启后端口漂移需更新扩展地址
- **桌面拾取错误中文化**：spy not started / nothing under cursor 映射为
  中文行动指引
- **填充模式行为修正（点选即写入）**：修复「提示将写入步骤 N 但必须再手点
  按钮、列表完成后无任何反馈」的交互脱节——填充模式下 element 事件到达
  即自动写入 target 并解除武装（版本号去重防重放）；list_done 自动填入
  行容器选择器；中间态 list 快照仅展示。面板 onPick 经 ref 稳定化，
  轮询 interval 不随渲染重建
- **定位器核心库化 + 引号缺陷修复**：选择器/XPath 纯函数抽取为
  locator-core.js（UMD 双端：浏览器注入 + Node 单测共用）；
  修复 xpathQuote 反斜杠转义产出非法 XPath 的缺陷（改标准 concat 拼接，
  含引号文本不再生成坏表达式）；16 条 Node 断言经 pytest 门禁
  （test_locator_core.py，node 缺失显式跳过）
- **抓取→循环闭环**：「生成抓取步骤」支持附带 foreach——extract_table
  output_context 命名数据 + 循环 source 预填 steps.<id>.rows（形状对齐
  scrape.build_scrape_steps；空循环体引擎安全），循环体在属性面板配置
- **列表上下文持久反馈**：匹配行保持虚线描边（此前 600ms 闪烁即逝），
  行悬停深色高亮
- **扩展 v2 —— 浏览器的影子（DevTools 级提取）**：内容脚本全量重写——
  DevTools 式检查（内容盒高亮+信息浮签+十字光标）、底部面包屑条逐级切换
  选中祖先、相似兄弟检测自动进入列表模式（整组高亮+计数）、行内字段采集
  （语义自动命名）；双定位器输出 CSS（穿透 open shadow root，>>>) 与
  XPath（id 锚定/文本兜底，shadow 内标注降级）；属性快照随包上报；
  iframe 全帧注入（allFrames）。协议 v2（kind=element|list|list_done）
  dict 透传向后兼容；面板分流渲染：单元素卡 css/xpath 切换复制、
  列表卡匹配徽标+可重命名字段 chips+3 行预览表；「生成抓取步骤」一键
  产出 browser.extract_table 入画布（复用现有 foreach 数据管线）
- **浏览器拾取 v2 —— Chrome 扩展通道（主）**：MV3 扩展（内容脚本 picker +
  Service Worker 回传），在用户真实浏览器的任意页面点选元素实时回传设计器，
  保留登录态与真实会话；`POST /api/browser_pick/event` 接收通道 +
  `GET /api/browser_pick/extension/download` zip 打包下载；面板重做为
  三步接入引导 + 实时元素卡片，URL 手输降级为 Playwright 沙盒次要入口
- **桌面拾取权限修复（报错根因）**：/api/spy/start 前置 ax_trusted 预检，
  未授权 409 返回精确指引并触发系统原生授权弹窗（此前 EventTap 线程内
  静默失败，UI 表现为无反应）；SSE 新增 error 帧；SpyPanel 错误态渲染
  「打开系统设置 · 辅助功能」深链（Electron bridge 新增 openExternal）
- 拾取会话上提为受控 hook useDesktopSpy：/api/spy/* 生命周期 + SSE hover +
  overlay 联动单点封装，SpyPanel 退化为纯展示组件
- 属性面板新增「从屏幕拾取」：参数含 element 的动作可一键启动拾取，
  捕获结果写入选中步骤 params.element（填充模式），未选中时维持追加行为
- **全局捕获快捷键**：spy 会话期间 Electron 注册全局键（F2，冲突降级 F6），
  焦点在任意应用均可触发捕获；window-all-closed 统一 unregisterAll
- **浏览器元素拾取（新能力）**：BrowserPickerService——Playwright 有窗
  Chromium 打开 URL + 注入 picker 脚本（hover 高亮 / 点击选取生成唯一
  css 选择器 / Esc 取消），/api/browser_pick/{start,result,stop} 三端点；
  前端「网页拾取」面板轮询展示，属性面板「从页面选取」填充 target 参数
- 根治「拖入步骤显示英文」：动作目录收敛为共享 hook useActionCatalog
  （react-query retry），消灭页面级无重试拉取在启动竞态下 catalog 永久为空的问题
- **保存/试运行陈旧 YAML 缺陷修复**：steps[] 为唯一真相源——保存前强制
  表单→YAML 同步（此前直接存 yamlText 旧值，未同步时会存出过期流程甚至
  "{}"）；打开试运行抽屉时自动同步，测试面板始终吃当前步骤
- 浏览器拾取集成测试 test_browser_picker.py ×4：本地 HTTP 夹具驱动真实
  注入链路（点击选取/Esc 取消/会话替换），chromium 缺失时显式跳过
- 流程图打磨：节点垂直脊柱对齐、行距 130、新增「整理布局 / 适配视图」控件；
  拖入悬停反馈由 border/ring 跳变改为底色着色

### 设计器重构
- 三栏 IDE 布局：左=动作库（目录/拾取/抓取）· 中=双视图（流程图主编辑面 /
  步骤列表）· 右=StepInspector 属性面板（选中步骤即改即存）
- React Flow 画布修复：全高画布、拖入高亮反馈、落点建节点、插入后自动居中、
  空态引导、MiniMap；节点单击选中联动属性面板，Delete 键删除（RF 内建删除禁用）
- 步骤列表升级：中文标题 + 动作名 + 参数摘要两行卡，悬停快捷复制/删除，
  排序与目录拖入保持
- YAML 编辑迁入底部抽屉；设计器路由全出血（AppLayout 去 padding/页脚）

### 动作目录中文化（186/186 label_cn 全覆盖）
- registries 补全 71 个缺失 label_cn（api/core/document 全域 + desktop/
  browser/dataops 缺口），目录支持中文搜索
- 新增 lib/actionDisplay.ts 单一出口：中文功能名主显、动作名副显（mono）；
  CatalogPanel 两行条目 + 域图标，画布节点显示参数摘要

### 清理
- 删除死代码：StepEditDialog（从未被触发的弹窗）、ParamsPanel（无引用）
- **修复构建遮蔽顽疾**：清除 src 下 34 个被误提交的陈旧 tsc 编译残留
  （*.js）——Vite 解析顺序 .js 先于 .tsx，导致源码改动长期不生效
  （画布无法拖拽等症状即源于此）；重建后 bundle 已验证包含全部新代码

## [0.14.0-poc] — 2026-08-24

Electron 现代化迁移 + 动作扩充。**418 pytest · 15 域 156 动作。**

### electron-vite 迁移（大爆炸式）
- CJS → TypeScript ESM 全链路（main/preload/renderer 三进程统一）
- `electron.vite.config.ts` 替代独立 vite.config.ts
- IPC 类型安全：IpcChannels 枚举 + ApaDesktopBridge 接口共享
- `pnpm dev` 一条命令启动三进程全栈（vite HMR + Python serve + Electron）
- 设计器 Tab 双视图：步骤列表(主编辑面) / 流程图概览——修复滚动断裂

### 新动作 ×8（138→156）
- db.sqlite.query / execute（stdlib sqlite3，零依赖）
- notify.dingtalk / wecom_webhook / feishu_webhook（群机器人 webhook）

## [0.13.0-poc] — 2026-08-24

Capability Pack 架构落地。**413 pytest · 15 域 152 动作 · AIP 协议零改动。**

### v0.13 Pack 体系（三层能力架构 L-Pack 层）
- apa_core/packs.py：PackManifest 契约 + 发现三通道
  （builtin→entry_points→~/.apa/packs 用户覆盖）+
  冲突治理（同名 action 默认拒绝，overrides[] 显式接管+审计）+
  instantiate_executor 延迟装配
- 存量 llm 迁移为首个标准包 packs/llm/（pack.yaml+actions/+executor）
  ——吃自己狗粮验证全链路
- serve/cli 装配：发现先于构造，registry 片段合并进 ServeApp 与
  create_app 双侧，executor specs 桥接 _build_executors 自动挂载
- doctor --packs 能力包清单 · 协议层零改动
  （pack 只是 registry 组织方式与 executor 装配方式）

## [0.12.0-poc] — 2026-08-24

RPA 基础功能收尾对标。**410 pytest · 15 域 152 动作。**

### P22-M1 流程控制收尾
- `for_times` 次数循环（编译为 range foreach，复用全部管线）
- `loop.infinite` 无限循环糖（max_iterations 默认=流程预算）
- 多条件/else-if 链文档模式验证

### P22-M2 相似元素 + Web 增强
- browser.get_similar_elements → foreach source（循环相似元素达成）
- browser.dialog_handle：一次性 alert/confirm/prompt 处理器
- browser.drag_drop

### P22-M3 DataTable 收尾
- delete_row / delete_column / clear / column_info(类型推断) /
  set_column_info(重命名+标注)

### P22-M4 OS 补全
- file.zip(递归+原子落盘) / file.unzip(zipfile-slip 防穿越)
- desktop.screenshot(region→PNG/ImageIO)
- process.kill(pid SIGTERM / pkill 模糊)

### P22-M5 交互+代码段
- ui.confirm：HITL 轻量确认卡（Gateway 拦截 + SUSPENDED + resolve 唤醒）
- **code.python**：subprocess 隔离 + timeout 强杀 +
  risk=L3 默认策略强制人工审批 + 完整代码审计
  （与 shell.execute L2 形成风险梯度）

## [0.11.0-poc] — 2026-08-24

范式跃迁启动：双环架构落地。**359 pytest · 138 动作 / 15 域。**

### Phase A 引擎控制流完备（编译目标语言）
- `loop.break` / `loop.continue`：LoopContext 深度追踪，嵌套循环
  语义正确；无栈使用显式 ProcessDefinitionError
- foreach 字典源 → {key,value} 迭代；while 支持 body_steps 子步骤
  （与 foreach 同构，控制流可用）
- **预算穿透**：循环体子引擎消耗并入全局 max_actions（修复此前
  子引擎独立预算的绕过漏洞）
- `if.*` 谓词查询族 ×6：element_visible/url_contains/
  text_on_screen(Vision)/file_exists/dir_exists/window_exists
- wait.file(glob) / wait.window(title) · desktop.humanize 模拟真人
  （贝塞尔轨迹+高斯点击延迟）
- AST 白名单 += 算术运算（循环条件 n % 2 等）
- Registry when_to_use 注解 pass（IntentCompiler 词表地基）

### Phase B 意图环 MVP（策略一：模板检索+槽位填充）
- IntentCompiler：模板检索评分 → LLM 填槽 → 未填占位符强制转
  澄清问题（兜底）→ LLM 失败优雅降级
- 场景模板库：price-monitor / cs-quality-check（keywords/slots/yaml）
- `POST /api/intent/compile`（注入式，未配置 501）
- 前端工作台（Workbench 替换 Assistant 路由）：对话主轴 +
  草稿卡片确认门 + sessionStorage 移交设计器画布

### Phase B 补充：策略二自由编译（同版本追加）
- FreeIntentCompiler：全 Registry 作为 LLM 词表（紧凑目录含
  risk/必填参数），任意自然语言 → process.yaml
- 双重校验硬拒绝：幻觉动作名（转澄清+引导描述效果）· 结构非法
  （空步骤/重复 id/C3）经既有 build_process 解析器兜底
- AutoIntentCompiler 自动路由：模板命中走策略一，未命中落自由
  编译；serve 有 Key 时自动装配（共享 LLMClient, timeout 30s）

## [0.10.0-poc] — 2026-08-24

审计修复 + 地基补缺 + 循环体可视化。**341 pytest · 14 域 131 动作 ·
电商运营场景矩阵 6/6 可落地。**

### P20-B UI 审计修复（8 项）
- **拖拽双插入根因修复**：步骤卡 onDrop 缺 stopPropagation 导致事件
  冒泡到画布再插入一次（用户报告的拖拽 bug 根因）
- Firefox DnD text/plain 兜底 · VarPicker fixed 定位逃逸弹窗裁剪 ·
  fitView 仅首挂（视图跳动根治）· 画布高度随节点包围盒自适应 ·
  目录搜索词跨 Tab 保留 · 排序拖拽虚线高亮反馈 · 左栏可折叠

### P20-A 地基补缺
- browser.iframe_switch/frame_reset：FrameLocator 穿透定位模型
- browser.storage_state_save/load：登录态跨次运行一行持久化
- llm.text 新域：classify(越权标签拒绝)/extract/summarize，
  DeepSeek-chat，离线 dependency_missing 优雅降级
- data.merge：concat 列并集 / inner|left join（JSON 规范键匹配）

### P20-C 循环体可视化编辑
- StepEditDialog 内嵌 LoopBodyEditor：foreach body_steps 增删改/
  上下移/参数 JSON——批量操作类场景全程 UI 搭建
- examples/ecommerce/: batch-reprice(S4) / cs-quality-check(S5) 模板

## [0.9.0-poc] — 2026-08-24

触发器与通道补全。**334 pytest · 14 域 125 动作。**

### P19-M1 运行详情真实化
- `GET /api/journal/records?session=` 按会话查询 journal（Runs 页
  「详细轨迹为 M2 增强」占位符退役）；前端结构化渲染终态/步骤/动作

### P19-M2 邮件收件
- `email.receive`：IMAP4_SSL 拉取，BODY.PEEK 默认不标已读，
  multipart text 提取 + RFC2047 头解码，limit/criteria/mark_seen 可控
  （Fake imaplib ×5 测试）

### P19-M3 文件监听触发器
- Scheduler 新增 watch 类型：glob mtime 快照比对，tick 驱动；
  新增/修改各触发一次，删除自动出快照
- serve kind=watch 热接线；Jobs UI 第三种触发方式（amber 徽标）
- E2E：新建文件 → tick → 会话 journal 终态

### P19-M4 OCR 等待
- `ocr.wait_text`：轮询定位屏幕文字直至出现或超时
  （text_timeout），bounds 入 ContextStore 供后续点击引用

## [0.8.0-poc] — 2026-08-24

决策贯通 + 调度管理。**324 pytest · 123 动作 · cascade_llm 从标签变事实。**

### P18-M1 内置 LLM 决策贯通
- ProcessRunner `decision_fn` 插槽 → ProcessEngine（C1 契约）
- serve `make_llm_decision_fn`：LLMClient 适配 + 每 Session 决策预算
  （默认 20，超出折叠 uncertain(budget_exhausted)）+ 异常兜底 +
  耗时审计入 journal meta
- ai_decision context 改用 render()——修复 lookup() 无法解析 {{}}
  模板的存量缺陷（decision_fn 首次真实接线即暴露）
- 占位 Key 防御：`KEY=# 必填…` 不再进入 environ 固化
  （根治 phase9 环境测试跨文件 flake 与真实 UX 污染）
- FakeLLMClient 三层注入测试（引擎/工厂/ServeApp E2E 分支命中）

### P18-M2 定时任务管理
- cron.next_after：分钟精度下次触发（月/小时跳跃优化；2月30日类
  不可能表达式抛 CronError）
- ServeApp 任务规格 CRUD：热替换调度器条目 + scheduler.yaml 原子写；
  run_job_now 立即触发
- API ×4：GET /api/jobs、POST save、DELETE、POST run（serve 注入，
  非 serve 模式 501）
- Runs 页 → 运行中心双 Tab：定时任务卡片列表（kind Badge/expr/
  next_run/流程缺失标记）+ 新建编辑 Dialog + 立即运行

### P18-M3 设计器拆分
- StepNode / EngineChip 抽为独立组件；删除双类型系统死代码
  （designerStore/designerTypes 旧桩）

## [0.7.0-poc] — 2026-08-24

影刀级交互底座 + 决策引擎完整接入。**304 pytest · 14 域 123 动作 ·
doctor 15 项 · CI 暂停（重构期）。**

### P17 设计器重构（R1）
- `components/ui/` 零依赖设计系统：Button/Dialog(ESC+点外关)/Drawer/
  Badge/Input 等统一 token（zinc 主色、focus ring、11px/xs/sm 层级）
- **影刀式 StepEditDialog**：单击步骤 → 弹窗编辑（风险 Badge 头部 +
  SchemaForm + 「高级选项」折叠），替代右侧逐字段面板
- 右栏移除改双栏；试运行入底部抽屉；拾取/抓取向导收为左栏 Tab；
  画布节点白底卡片+类型色条+序号徽标；全部 emoji 清零，图标 lucide 化

### P17 dsh 完整接入（R2/R3）
- **SDK 竞态修复**：WsClientTransport.onOpen setter 语义——回环连接
  先于赋值 OPEN 导致 hello 静默丢失
- WsGatewayServer 动态会话池：register_session 运行期调度建泵；
  跨线程 enqueue 经 call_soon_threadsafe 投递（嵌入式模式根治）
- tenant §12.1 透传（config→hello 帧）
- serve 内嵌 WS 网关（--ws-port 8765 / --no-ws）+ 会话动态注册 +
  外部 agent 身份白名单
- plugins/dsh/run-agent.mjs 正式宿主（零 cordis 依赖）：
  DeepSeek HTTP adapter / --mock 确定性决策
- ai_status 真实化（env 探测 cascade_llm|rules_only）+
  Settings「决策引擎」区块 + 设计器顶栏三态 chip

[0.7.0-poc]: https://github.com/emVisible/AIP/tree/poc

## [0.6.0-poc] — 2026-08-24

RPA 指令集大扩充 + 影刀级交互底座。**302 pytest · 14 域 123 动作 ·
doctor 15 项 · CI 暂停（重构期）。**

### P16 指令扩充（60 → 123）
- **M1 数据工具包**：string×10(regex/模板/pad) encode×4(base64/url) json×2
  dt×5(now/parse/add/diff/timestamp-UTC) hash×3(已知向量) data增强×4
  （aggregate/distinct/slice/json_to_table 可链式）——修复 serve 从未挂载
  数据执行器的存量缺口
- **M2 流程控制**：while 循环（max_iterations 死循环守卫 + 预算双保险 +
  三态条件求值器：键缺失=乐观进入的轮询语义）、log 节点、core.delay(300s 上限)、
  data.count
- **M3 浏览器高级**：多标签页管理（旧动作零破坏）、upload、download
  双模式（URL 带 Cookie / expect_download 触发捕获）、execute_js、
  cookies×3、hover/double_click/right_click、get_page_info、element_attr
- **M4 Excel 高级+系统**：样式/合并单元格/列宽/柱状折线图表/sheet 生命周期/
  find_replace/行列插入删除 ×10；shell.execute(timeout 强杀+审计 cmd)、
  sys_notify、clipboard×2、file.list_dir/mkdir/exists/stat

### P15 影刀级底座（同版本包含）
- M1 macOS AX 元素识别：hit_test/ax_path 三级重定位恢复（标题锚点+几何
  包含搜索）/双路径点击（AXPress→坐标兜底）；Apple Vision OCR
  （screen_text/click_text）；doctor 权限检查（辅助功能/屏幕录制）
- M2 桌面拾取器：EventTap 节流监听 → SSE hover 流 → Electron 透明 overlay
  高亮 → SpyPanel 捕获即步骤
- M3 数据抓取向导：点两行推断行选择器（shared_class/bare_tag/nth 三级），
  列相对路径配置，活页预览，一键生成 extract_table(+foreach)
- M4 设计器拖拽：目录拖入画布光标落点建节点、步骤卡拖拽排序（位置持久化）、
  右键复制/插入/删除；ReactFlowProvider 拆分

### 工程决策
- CI 暂停（`78680ca`）：重构期节省 Actions 额度，稳定后 revert 恢复
- C3 全程合规：非幂等动作（dt.now/uuid/rename/delete/shell…）none+retries=0；
  同参重放幂等者 required

## [0.5.0-poc] — 2026-08-23

poc 分支首个完整功能面。**202 pytest · APA-Profile conformance 20/20 ·
doctor 13/13 · 54 注册动作 / 11 域 · tsc strict 清洁 · dmg 可分发。**

### AIP 协议与核心（v0.1–v1.0）
- AIP Kernel v0.1 规范 + JSON Schema + Python SDK（信封/四消息/逐流序列/会话）
- APAGateway 六步校验链：信封→版本→I9 来源绑定→Session→序列→Registry
  查找→Schema→权限→状态→C4 凭据扫描→风险策略→审计→重试调度
- Action Registry（YAML，C3 单一来源）· PolicyConfig 风险分级 · Session 状态机
- EmbeddedGateway 模式 C（进程内回路，§13.2）

### 执行器（apa-executors）
- Browser（Playwright）：navigate/click/input/select_option/wait/scroll/
  screenshot/extract/**extract_table 结构化抓取**
- Desktop（macOS Quartz CGEvent 原生键鼠/窗口）
- API（httpx）：GET/POST/PUT/PATCH/DELETE + Vault 凭据注入（C4）
- Document：extract_text / extract_fields / classify
- Data：create/filter/sort/to_csv 内存表格管道
- Excel（openpyxl）：read_range / append_row / **append_rows** / write_cell /
  get_formula / set_formula / list_sheets / add_sheet，原子落盘
- Email：SMTP+TLS+附件+CC
- OCR：mock 后端 + http_ocr 云接入点（兼容 {text}/{data:{text}}/OpenAI 格式，
  C4 凭据注入）

### 流程引擎
- ProcessEngine：条件跳转 / error handler / max_actions 预算（§10.2）
- **foreach 循环**（source 数组 → body_action 逐项执行，µs 级/项）
- **sub_process 子流程调用**（process_loader 注入、变量作用域合并、预算透传）
- ai_decision 决策节点（P2：AI 不持执行权）
- `.flow` 动词句 ↔ process.yaml 双向编译器

### 控制平面
- Scheduler：cron（5 字段纯 stdlib）+ event 触发器 + scheduler.yaml 批量加载
- ServeApp 常驻栈：面板 + 调度循环 + 本地执行单进程
- FastAPI API 层（17 路由）：processes/templates/registry/sessions/analytics/
  events(SSE)/recorder
- Webhook 触发闭环 E2E：POST /api/events → 调度器 → 流程执行 → 回调命中
- Vault 凭据管理 · Analytics 报表 · HITL 审批任务

### 前端与桌面（React 18 + TS strict + Electron 37）
- 三面板低代码设计器：动作目录（11 域搜索）/ React Flow 画布 /
  Schema 属性面板 + 试运行；foreach/sub_process/ai_decision 一键插入预填骨架
- **浏览器操作录制器**（影刀同款体验）：URL 输入 → 有头浏览器实时捕获
  click/input/select（世代号去重解决 set_content 监听器丢失难题）→
  停止即导入画布；REST 会话 API + 事件计数轮询 UI
- 模板库：数据抓取报表 / 批量审批，一键导入改造
- Dashboard / Runs / HITL / Settings 页 + SSE 实时流
- **Electron 打包**：PyInstaller 冻结 apa_server（uvicorn 动态链 hidden imports，
  registries/templates 进 _internal），dmg 167MB 跨机分发；
  dev/packaged 双模式 main.cjs，可写数据落 userData

### 工程化
- `apa doctor` 13 项自检（依赖/Chromium 实启/registry 加载/目录可写…，
  曾当场抓出 excel.yaml 两处 C3 违规）
- 基准：latency p50/p95/p99 + data_throughput（10k 行管道 ~4ms、
  千次 foreach、Excel 万行写读）
- CI：Python 3.12/3.13 矩阵（对齐 requires-python）、e2e marker 注册、
  starlette 缺失优雅跳过、pnpm 缓存修正
- dsh 插件容器挂载验证 + 跨语言 E2E

[0.5.0-poc]: https://github.com/emVisible/AIP/tree/poc