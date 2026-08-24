# Changelog — APA (Agentic Process Automation)

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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