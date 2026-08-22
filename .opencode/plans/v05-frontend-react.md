# v0.5-Frontend：React + TypeScript 前端重构计划

> 状态：待执行（全部决策已确认）
> 组件库：shadcn/ui 风格（Radix + Tailwind CSS v4）—— 已确认
> 零依赖 Studio 处置：React 版验收通过后**直接退役**，不留 fallback —— 已确认
> 决策确认：React+TS 现代化重构 · 架构兼容 dsh · 简约现代 UI · 组件化对齐
> 前置：Phase 1–11 后端能力全部就绪（REST API 完整覆盖）

---

## 一、背景与决策

用户决策：应用采用现代化前端技术（**React 18 + TypeScript**），彻底重构，架构兼容 dsh。

调研确认：**dsh web 前端本身就是 React 18 + TS + Vite** —— 技术栈完全同构，
"兼容 dsh 架构"在前端侧即：采用相同的分层模式与构建工具链，用主流生态
替代 dsh 私有包。

## 二、dsh 前端架构调研结论

```
apps/web (thin bootstrap main.ts)
  └─ client/web          应用壳 AppWebEntry
      ├─ client/ui-primitives   React 组件库（react ^18.2, clsx, shiki…）
      ├─ client/connection      浏览器↔host 连接层（ws + schemastery 契约）
      └─ host/apiproxy          传输无关 wire contract
          └─ host/webserver     HTTP 路由载体
              └─ frontend-static SPA 静态服务
```

**对齐策略**：APA frontend 采用相同四层模式，用主流生态替代 dsh 私有包：

| dsh 概念 | APA 对应实现 |
|---|---|
| `client/connection`（ws+schemastery） | TanStack Query v5 + SSE（EventSource）|
| schemastery API 契约 | zod schema + TypeScript 类型推导 |
| `client/ui-primitives` | shadcn/ui 风格组件（Radix + Tailwind CSS v4）|
| `client/web` AppWebEntry | 自研 `App.tsx` 路由壳 |
| cordis inject DI | zustand store + React Context |

## 三、技术栈选型

| 关注点 | 选型 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript strict | 对齐 dsh；生态最大 |
| 构建 | Vite 6 | 与 apps/web 同构；HMR 快 |
| 包管理 | pnpm workspace | 用户指定 pnpm |
| 样式 | Tailwind CSS v4 | 简约现代、原子化、组件化基础 |
| 组件 | shadcn/ui 风格（Radix 无头组件自建）| 可定制、不锁死视觉 |
| server state | TanStack Query v5 | journal 轮询/SSE 刷新/缓存 |
| client state | zustand | 轻量、无样板 |
| 路由 | react-router v7 | 标准 |
| 表单 | react-hook-form + zod | registry schema → zod 动态生成参数表单 |
| 流程画布 | @xyflow/react (React Flow) | 低代码可视化编辑器标准实现 |
| 图表 | recharts | Analytics 指标卡 |

## 四、目录结构

```
apa/
├── pnpm-workspace.yaml           # packages: [frontend, desktop]
├── frontend/
│   ├── package.json              # react/react-dom/@tanstack/query/zustand/
│   │                             # @xyflow/react/react-hook-form/zod/recharts
│   ├── vite.config.ts            # dev: proxy /api → http://127.0.0.1:8686
│   ├── tailwind.config.ts
│   ├── tsconfig.json             # strict
│   ├── index.html
│   └── src/
│       ├── main.tsx              # thin bootstrap（对齐 dsh main.ts 模式）
│       ├── App.tsx               # Router + QueryClientProvider + Layout
│       ├── api/                  # apiproxy 模式：类型化客户端层
│       │   ├── client.ts         # fetch 封装 + ApiError 类型
│       │   ├── types.ts          # SessionSummary / ProcessInfo / ActionMeta / StepTrace …
│       │   └── endpoints/        # sessions.ts / processes.ts / events.ts /
│       │                         # hitl.ts / analytics.ts / registry.ts
│       ├── hooks/                # useSessions / useProcess / useJournalStream(SSE) /
│       │                         # useActions / useResolveTask
│       ├── store/                # zustand：designerStore(画布状态)/uiStore
│       ├── pages/
│       │   ├── Dashboard.tsx     # 会话卡片 + 指标 + SSE 实时流
│       │   ├── designer/         # 低代码设计器（M-B 核心）
│       │   │   ├── DesignerPage.tsx    # React Flow 画布 + 属性面板 + 目录 + 试运行
│       │   │   ├── FlowCanvas.tsx      # 节点/边渲染 + 连线规则
│       │   │   ├── StepNode.tsx        # 步骤节点组件
│       │   │   ├── ParamsPanel.tsx     # schema→zod 动态参数表单
│       │   │   ├── CatalogPanel.tsx    # 动作目录（搜索/schema 预填）
│       │   │   └── TestRunPanel.tsx    # 沙盒试运行轨迹
│       │   ├── Runs.tsx          # 运行历史 + 轨迹展开
│       │   ├── Hitl.tsx          # 审批中心（批准/驳回/重试）
│       │   ├── Assistant.tsx     # AI 助手状态页
│       │   └── Settings.tsx      # 注册表浏览/token/租户
│       └── components/
│           ├── layout/           # Sidebar/Header/Statusbar
│           └── ui/               # shadcn 生成的基础组件
└── desktop/                      # Electron（M1 骨架已有；改加载 frontend/dist）
```

## 五、API 层设计（apiproxy 模式对齐）

```typescript
// api/client.ts — transport-independent wire contract
export class ApiError extends Error {
  constructor(public status: number,
              public code: string,
              public detail?: string) { super(code); }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status,
    body.error ?? body.code ?? "unknown", body.message ?? body.detail);
  return body as T;
}
```

类型定义（`api/types.ts`）从 Python serve 的响应结构手工镜像
（后续可加 openapi-typescript 自动生成——后端补 OpenAPI spec 时启用）。

## 六、页面与路由

| 路由 | 页面 | 数据源 |
|---|---|---|
| `/` | Dashboard | GET sessions + analytics + **SSE** journal/stream |
| `/design/:id?` | Designer | processes CRUD + test + registry/actions |
| `/runs` | Runs | journal records 聚合查询 |
| `/hitl` | HITL 审批中心 | tasks resolve POST |
| `/ai` | AI 助手状态 | env 配置信息（新增 GET /api/ai/status）|
| `/settings` | Settings | registry actions + token/tenant 管理 |

## 七、后端补充需求（Python serve 配合）

1. **SSE 实时推送**：`GET /api/journal/stream?session=<sid>`
   → text/event-stream 推送增量 journal 记录（替代前端 3s 轮询）
2. **运行历史聚合查询**：`GET /api/runs?limit=20&status=completed`
3. **进程删除**：`DELETE /api/processes/<id>`（真相源文件删除）
4. CORS：dev 用 Vite proxy 免除；生产 Electron 同源——无需后端改动

## 八、实施阶段

### M-A 脚手架 + 监控页（可演示验收）
pnpm workspace 建立；Vite+Tailwind+Router+Query+zustand 初始化；
Dashboard 页接真实数据；SSE hook；
**验收**：`pnpm dev` 打开即见真实会话数据；事件触发实时刷新

### M-B 设计器画布版（低代码核心升级）
React Flow 画布替换表单式步骤列表：
节点=步骤、条件边=on_failure goto、错误跳转边着色区分；
节点点击→右侧 schema 参数面板（zod 动态表单）；
动作目录侧栏保留（搜索/schema 预填）；YAML 双向同步保留；
沙盒试运行轨迹面板保留。
**验收**：从零在画布上建 po_approval 同款流程并试运行成功；
保存后 serve 可调度执行同一 YAML。

### M-C 全页补齐 + Electron 集成
Runs/HITL/AI/Settings 四页迁移；desktop 改加载 frontend/dist；
零依赖 Studio HTML 退役（或保留 `--legacy` fallback flag）；
**验收**：桌面壳内完成全部操作路径，无功能回退。

## 九、验证门禁

- `tsc --noEmit` strict 通过
- eslint（新配置 flat config）
- vitest 单测（api/hooks/关键组件渲染）
- Playwright e2e：designer 建流程→试运行→保存 冒烟路径
- 后端全量 pytest 回归（132 通过基线不降）

## 十、风险与非目标

| 风险 | 对策 |
|---|---|
| React Flow 学习曲线 | 文档完善、示例丰富；风险低 |
| Tailwind v4 较新 | 如遇问题可锁 v3.x |
| cordis rc 类型缺陷影响前端类型引用 | 前端不 import cordis 类型（仅运行时容器使用插件）|

非目标：SSR、移动端适配、多主题切换、国际化框架（中文硬编码延续 POC 惯例）。

## 十一、与现有零依赖 Studio 的关系

| 阶段 | vanilla Studio | React frontend |
|---|---|---|
| M-A/M-B | 保留为 `/legacy` fallback | 主入口 |
| M-C 之后 | 退役（代码归档）| 唯一 UI |

后端 REST API 不变——两套 UI 消费同一数据面，无双真相源。