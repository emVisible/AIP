# v2.0-M1 实施计划：桌面壳 + dsh 底座独立决策服务

> 状态：待执行（权限恢复后按此文档直接实施）
> 前置：Phase 1–11 已完成并推送（`2fd1f2f`）；cordis 4.0.0-rc.8 已装入 `apa/plugins/dsh`
> 决策确认：Studio 主界面 + 本机 Python 自举 + `.flow` 纳入 M2

---

## 目标

v2.0-M1「能跑的桌面壳」：
1. Electron 桌面应用：窗口 + 三子进程编排（Python serve / dsh decision worker / 可选 dsh host）+ 崩溃重启
2. `decision_worker.mjs`：dsh 底座独立决策服务（DeepSeek REST / MOCK 双模）
3. Studio「AI 助手」导航页签
4. 验收：`pnpm desktop` → 窗口打开 → 面板+设计器可用 → demo 流程跑通 → AI 助手页签显示配置状态

## 非目标

拖拽画布、PyInstaller 打包（M3）、Windows UIA、RF 全库桥接、dsh web 前端嵌入（M2 评估 iframe 方案）

---

## 一、decision_worker.mjs（dsh 底座独立工件）

位置：`apa/plugins/dsh/decision_worker.mjs`

### 职责
以 cordis 容器加载 @apa/dsh-plugin（与桌面应用/harness 同路径），经 AIP WebSocket 连接 APA 网关，事件交给 LLM（DeepSeek OpenAI-compatible REST）决策。

### 运行模式
| 条件 | 行为 |
|---|---|
| DEEPSEEK_API_KEY 已配置 | 真实 LLM 决策 |
| MOCK_LLM=1 | 脚本化决策（测试/演示）|
| 两者皆无 | 打印说明后 exit 0（上层降级规则引擎）|

### 接口
```
node decision_worker.mjs \
  --url ws://127.0.0.1:8765 \
  --session s_po_001 \
  --source decision_worker_001 \
  --allowed browser.click,erp.order.approve,human.task.create
```

### 关键实现要点
1. **.env 加载**：从脚本位置向上查找 .env（最多 6 层），parseEnvFile 支持 export 前缀/引号/注释；不覆盖已有环境变量。注意：第一版草稿中的正则 `/^export\s+)?^([A-Z0-9_]+)=.../` 有语法错误——改用 `indexOf("=")` 切分实现（已在思考中验证过的 parseEnvFile 版本）
2. **LLM 适配**：fetch POST `{BASE_URL}/chat/completions`，model=DEEPSEEK_MODEL||deepseek-chat，temperature=0；响应取 choices[0].message.content
3. **MOCK 模式**：提示词中出现的第一个 allowed 动作即决策；无匹配返回 uncertain
4. **cordis 挂载**：`const { Context, Service } = await import("cordis")` → MockDeepSeekService extends Service(ctx,"llm") 含 complete({messages}) → app.llm = new Service(app) → app.plugin(apaPlugin dist, config)
   - 注意：需动态 import("cordis") 与 import("../dist/index.js")（ESM）
   - 插件 dist/index.js 导出 name/inject/apply ✓ 已编译
5. **保活**：`setInterval(() => {}, 1 << 30)` 或长 sleep；由上层杀进程退出
6. **防御**：allowed 为空数组时不做 LLM 调用直接 uncertain

### 已知设计细节（避免重踩）
- agent.ts 的 onMessage 会将 gateway 回执（hello-ack seq=1 / pong 无 seq）送入 peer.handle —— Receiver 对无 seq 帧返回 gap，GapTolerantReceiver 未装在 node 侧 → **hello-ack/pong 帧会被静默忽略（可接受，不影响功能）**
- decide() 的 prompt 由 agent.ts 组装（含 SYSTEM_PROMPT + JSON payload），llmDecide 收到的 prompt 字符串包含 expectEvent 名称 ✓ MOCK 匹配可用
- 散文包裹的 JSON 由插件侧 parseDecision 防御解析 ✓

---

## 二、desktop/ Electron 应用

### 目录结构
```
desktop/
├── package.json          # name=apa-desktop, main=main.js, devDeps: electron
├── main.js               # 编排入口
├── preload.js            # contextBridge 最小暴露
└── lib/
    ├── bootstrap.js      # Python 自举（webui.sh 逻辑移植）
    └── sidecar.js        # 子进程 spawn/健康检查/重启
```

### main.js 编排流程
1. `app.whenReady()` → 显示加载窗口（loading.html 或 data URL）
2. `ensurePython()`（bootstrap.js）：
   - 找 python3/python → 建 apa/.venv → pip install -e 各包 + pyyaml/jsonschema/httpx/websockets
   - 幂等：apa_core 可导入即跳过（与 webui.sh 一致）
3. 选空闲端口（net.createServer listen(0)）
4. spawn serve sidecar：`$PY -m apa_core.cli serve --port P --journals apa/data/**/*.jsonl --processes-dir apa/data/processes --runs-dir apa/data/runs`
   - 日志写 userData/logs/serve.log
   - 健康检查：轮询 GET /api/processes 直到 200（60s 超时）
5. spawn decision worker（条件启动）：`node plugins/dsh/decision_worker.mjs --url ws://127.0.0.1:P+1 ...`
   - WS 端口：ServeApp 需扩展 WsGatewayServer 启用（见下方「serve.py 待补」）
   - 无 Key 且非 MOCK → 不启动
6. 创建 BrowserWindow 加载 http://127.0.0.1:P
7. sidecar 崩溃 → 指数退避重启（max 5 次）；窗口关闭 → tree-kill 全部子进程 → app.quit()

### bootstrap.js 要点（webui.sh 移植）
- python3 (darwin/linux) / python (win32) 探测顺序
- venv 路径固定 apa/.venv
- 幂等安装检查命令：`python -c "import apa_core, yaml, jsonschema, httpx"`
- 失败输出实时转发到加载窗口（IPC → renderer 显示进度）

### serve.py 待补（本计划前置小改动）
ServeApp 当前仅 HTTP；WS 多会话网关未接入。decision_worker 需要 WS 网关才能连。
最小改动：ServeApp.__init__ 增加 `ws_port=None` 参数 → 非 None 时创建 WsGatewayServer(gateways 注册表) 并 start()；
_run_session_job 完成后将 runner.gateway 注册进 server.gateways 使 worker 可路由到对应会话。
（多会话池已支持动态添加？当前 gateways 在构造时固定——需加 `server.add_gateway(sid, gw)` 方法 + pump 任务补充。）

⚠️ 这是本计划中唯一的架构级新代码，预计 ~40 行。备选简化方案：
decision_worker 不走 WS，改经 HTTP POST /api/events + 轮询 /api/sessions 获取事件——但失去实时性，
且与已验证的 AIP WS 路径不一致，不推荐。

---

## 三、Studio「AI 助手」页签

### 后端
- StudioServer 构造参数增加 `ai_status_provider=None`（callable → dict）
- serve.py 注入：返回 `{mode: "deepseek"|"mock"|"rules_only", model, key_configured: bool}`

### 路由
- `GET /ai` → 页面：显示 LLM 配置状态、模型名、连接方式说明
- Studio header 加导航链接 `<a href="/ai">AI 助手</a>`（与「← 监控面板」同排）

### 页面内容（零依赖，风格同 Studio）
- 配置状态卡片（key_configured ✓/✗、model、base_url）
- 设置指引：编辑仓库根 `.env` → DEEPSEEK_API_KEY=... → 重启生效
- （M2）对话式交互入口占位

---

## 四、测试计划

### test_phase12.py 新增
1. **TestDecisionWorker**
   - e2e：EmbeddedGateway + BrowserExecutor(MockPage) + WsGatewayServer；
     spawn `node decision_worker.mjs --url ... --session ... --allowed browser.click`
     env MOCK_LLM=1 → push page.loaded → assert clicked==["approve-btn"] & rc==0
   - 无 Key 无 MOCK → rc==0 且日志含「优雅退出」
   - allowed 不匹配 → uncertain 路径（human.task.create 被 gateway 拦截 SUSPENDED）
2. **TestServeWsGateway**
   - ServeApp(ws_port=0) → WsGatewayServer 就绪 → add_gateway 动态注册会话
   - decision worker 经 WS 连接该会话完成闭环
3. **TestAiPage**
   - GET /ai 200 包含「AI 助手」「DEEPSEEK_API_KEY」
   - header 导航链接存在

### 回归门禁
全量 pytest + conformance + po-approval 示例 + webui smoke

---

## 五、执行顺序（权限恢复后）

1. serve.py 补 WS 网关集成（~40 行 + add_gateway 方法）→ 单测
2. decision_worker.mjs 写入（~150 行，设计见上）→ 手动冒烟（MOCK_LLM=1 + serve）
3. test_phase12.py 三组测试
4. desktop/ Electron 应用五文件 → `pnpm install && pnpm start` 手动验收
5. Studio /ai 页面 + 导航链接
6. README 生产表补桌面行 + CHANGELOG Phase 12
7. 全量回归 → 提交推送

## 六、风险备忘

- electron 二进制下载依赖网络（此前 cryptography 安装失败先例）——失败则先交付
  decision_worker + serve.py 改动（步骤 1–3、5），Electron 步骤挂起待网络恢复
- cordis rc 类型缺陷已绕（结构化 MinimalCtx），不影响运行时
- Windows path 差异：bootstrap.js 用 process.platform 分支处理 python 可执行名
