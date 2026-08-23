# Changelog — APA (Agentic Process Automation)

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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