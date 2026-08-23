# APA — Agentic Process Automation

基于 [AIP 协议](../../README.md)（AI Interaction Protocol Kernel v0.1）的企业级智能流程自动化系统 POC。

设计文档：[`APA_Design_Document_v2.md`](../APA_Design_Document_v2.md)（§ 引用均指向该文档）

```
传统 RPA：  录制 → 规则 → 执行 → UI变化 → 崩溃 → 人工维护
APA：       语义事件 → AI决策（最小上下文）→ 可靠动作 → 协议级恢复 → 自愈
```

**当前状态**：`poc` 分支，192 pytest 通过 · conformance 20/20 · 11 个动作域
45 个注册动作 · React 设计器 + 浏览器录制器 · Electron 桌面打包 · `apa doctor` 全绿。

## 核心不变量

| 约束 | 含义 |
|---|---|
| P1 | 语义优先，永远不传遥测/DOM/截图 |
| P2 | AI 永远不持有最终执行权（Gateway 校验链不可绕过） |
| C3 | idempotency/risk 只来自 Action Registry，禁止消息携带 |
| C4 | 凭据禁止进入任何 AIP 消息 payload（Vault 执行器内解析） |
| C5/C6 | 大对象只传引用；VLM 在 Executor 本地终止 |
| C7 | Session 状态在 Gateway 侧，Decision Engine 无状态 |
| CoD-1/2/3 | 事件 data ≤ 4KB；context.get 禁 `["*"]`；ContextStore 由 Executor 持有 |

## 五分钟上手

```bash
cd apa
python3 -m venv .venv && .venv/bin/pip install -e packages/apa-core \
  -e packages/apa-executors -e ../sdk/python fastapi uvicorn pyyaml httpx openpyxl playwright
.venv/bin/playwright install chromium          # 浏览器录制/自动化需要

# ① 自检：13 项环境验证（依赖/Chromium 实启/registry 加载/目录可写）
.venv/bin/python -m apa_core.cli doctor --check-browser

# ② 录制：操作浏览器 → 自动生成 process.yaml（影刀同款体验）
.venv/bin/python -m apa_core.cli record https://erp.example.com/orders \
    --process-id monthly_report --out data/processes/monthly_report.yaml

# ③ 运行常驻服务（FastAPI + 调度器 + 本地执行 + MockERP 沙盒）
.venv/bin/python -m apa_core.cli serve --port 8686 --journals 'data/*.jsonl'
# → http://127.0.0.1:8686 打开设计器 / 运行 / HITL 审批
```

Webhook 触发已就绪：

```bash
curl -X POST localhost:8686/api/events \
  -H 'Content-Type: application/json' \
  -d '{"name":"webhook.order.created","data":{"order_id":"WH-777"}}'
```

桌面应用（macOS）：

```bash
cd frontend && pnpm install && pnpm dist:dir   # → release/mac-arm64/APA Desktop.app
```

## 动作域总览（45 actions）

| 域 | 动作 | 后端 |
|---|---|---|
| string ×12 | regex_extract/replace/test · trim/upper/lower · format_template · pad · starts_with · contains · replace/split | 纯函数 |
| encode ×4 | base64_encode/decode · url_encode/decode | stdlib |
| json ×2 + dt ×5 | parse/stringify · now/parse/add/diff/timestamp(UTC) | stdlib |
| hash ×3 | md5 / sha256 / uuid_gen | 已知向量测试 |
| data ×9 | create/filter/sort/to_csv/count/aggregate/distinct/slice/json_to_table | 内存表格管道 |
| file ×6 | read_text/write_text/list_dir/mkdir/exists/stat | pathlib |
| shell ×1 | **shell.execute**(timeout 强杀+审计 cmd) | subprocess |
| system ×3 | sys_notify(通知中心) / clipboard_set/get(pbcopy) | darwin 优先 |
| browser ×24 | 导航/点击/输入/选择/等待/滚动/截图/提取/**extract_table** · **tab×4** · upload/download(expect_download) · execute_js · cookies×3 · hover/double_click/right_click · get_page_info/element_attr | Playwright 多页 |
| excel ×18 | 读/写/追加(单行+批量)/公式/sheet 列表 · 样式/合并/列宽/**图表** · rename/delete/copy_sheet · find_replace · insert/delete_row | openpyxl 原子落盘 |
| ocr ×2 | extract(mock/http_ocr) / screen_text(Apple Vision) | C4 凭据注入 |
| desktop ×17 | 窗口/键盘/文件/进程 · **AX 元素**: ui.read_element/read_tree/click_element/wait_element · click_text(Vision 定位) | Quartz + AXUIElement 双路径 |
| api/erp/session ×9 | HTTP 五动词 · MockERP 审批 · 会话收束 | Vault 注入(C4) |
| 流程控制（引擎内建） | if/goto/max_actions · foreach · **while(max_iterations 守卫)** · sub_process · ai_decision · log 节点 · core.delay | ProcessEngine |
| 治理 ×4 | human.task.create/cancel/reassign · session.complete | HITL/journal |

## 流程控制（ProcessEngine）

```yaml
process:
  id: monthly_report
  trigger: { type: event, name: cron.monthly }   # manual / cron / event
  max_actions: 100                                # §10.2 预算守卫必填
  steps:
    - id: scrape
      action: browser.extract_table               # 结构化抓取
      params: { row_selector: "table.orders tr",
                columns: { order_id: ".id", amount: ".amt" } }

    - id: big_only
      action: data.filter                         # 过滤大额订单
      params: { column: amount, op: ">", value: 10000 }

    - id: loop                                    # foreach 循环
      type: foreach
      params:
        source: "{{steps.big_only.rows}}"
        item_var: row
        body_action: erp.order.approve
        body_params: { order_id: "{{row.order_id}}" }

    - id: validate                                # 子流程复用
      type: sub_process
      params: { process_id: order_validation, input: { src: monthly } }

    - id: ai_pick                                 # AI 决策节点（P2：不执行）
      type: ai_decision
      params: { context: ["{{event}}"], available_actions: [approve, reject] }

    - id: report                                  # 邮件报表
      action: email.send
      params: { to: boss@example.com, subject: "日报 {{steps.big_only.count}} 笔" }
```

`.flow` 动词句格式与 process.yaml 双向互转：
`apa flow-compile x.flow && apa flow-decompile x.yaml`。

## 低代码设计器 + 录制器

React 18 + React Flow 三面板设计器（serve 模式内置）：

- **目录区**：11 域动作搜索 + 流程控制节点（foreach/sub_process/ai_decision）一键插入并预填骨架
- **画布**：步骤卡片拖拽编排；属性面板 Schema 表单编辑；试运行面板
- **模板库**：内置场景（数据抓取报表 / 批量审批），一键导入改造
- **🎙 录制器**：输入 URL → 操作真实浏览器（点击/输入/下拉实时捕获，
  事件计数轮询）→ 停止即生成流程导入画布。选择器策略：
  `data-apa-id > #id > [name] > [aria-label] > tag.class`

## 架构组件

```
apa/
├── registries/*.yaml         # 7 registry 文件，45 动作（C3 单一来源）
├── templates/*.yaml          # 场景模板库
├── packages/
│   ├── apa-core/             # Gateway 六步校验链 / ProcessEngine(foreach/
│   │                         # sub_process/ai_decision) / Scheduler(cron+event)
│   │                         # / ServeApp 常驻栈 / Recorder / Vault / Analytics
│   ├── apa-executors/        # Browser/Desktop(Quartz)/API/Document/Data/
│   │                         # Excel/Email/OCR 执行器
│   └── apa-sdk-python/       # AIPExecutor 基类（幂等守卫/context.get 免费提供）
├── frontend/                 # React SPA + Electron 壳 + electron-builder 配置
├── benchmarks/               # latency(动作往返 p50/p95/p99) + data_throughput
│                             # （10k 行表格 4ms · 千次 foreach µs级/项）
├── conformance/run.py        # APA-Profile 合规 20 用例
└── tests/                    # 192 pytest（含真实浏览器录制 E2E、webhook E2E）
```

### Gateway 校验链（§8.2）

信封 → 版本 → I9 来源绑定 → Session → 序列 → Registry 查找 → Params Schema
→ 权限 → Session 状态 → C4 凭据扫描 → 风险策略 → 审计 → RetryScheduler → 转发。

### 自定义执行器（30 分钟指南 §14.3）

```python
from apa_sdk import AIPExecutor

class MyExecutor(AIPExecutor):
    def _execute_action(self, name, params):
        if name == "my.action":                 # 在 my-registry.yaml 声明
            return True, {"done": True}
        return False, {"code": "action_not_supported_by_executor"}

    def start_observation(self):
        ...  # self.emit(name, data) 发语义事件（data ≤ 4KB，CoD-1）
```

## REST API 一览（serve 模式）

```
GET  /api/processes              POST /api/processes/save
GET  /api/processes/get/{id}     POST /api/processes/test        # 试运行
GET  /api/templates              GET  /api/registry/actions
GET  /api/sessions               GET  /api/analytics
POST /api/events                 # ← webhook 触发入口
POST /api/recorder/start         GET  /api/recorder/status/{sid}
POST /api/recorder/stop/{sid}    # → 返回生成的 process YAML
GET  /api/journal/stream         # SSE 实时事件流
```

## 性能基准（M 系列）

```bash
.venv/bin/python -m apa_core.cli latency --n 200     # 动作往返 p50/p95/p99
.venv/bin/python benchmarks/data_throughput.py       # 万行管道 / 千次循环 / Excel IO
```

| 路径 | 结果 |
|---|---|
| 数据管道 10k 行（create→filter→sort→csv） | ~4 ms |
| foreach 千次子流程迭代 | ~3.4 µs/项 |
| Excel 万行批量写 + 回读 | 写 20 批 4.7 s · 读 0.22 s |

## 开发

```bash
.venv/bin/python -m pytest tests/ -q            # 192 tests
.venv/bin/python conformance/run.py             # 20/20
cd frontend && pnpm exec tsc --noEmit           # TS strict 清洁
cd frontend && pnpm build                       # vite 生产构建
```

环境要求与更多细节见 [`QUICK_START.md`](QUICK_START.md)。