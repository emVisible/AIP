# Changelog — APA (Agentic Process Automation)

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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