# APA 架构宪法（Architecture Principles）

> 地基原则服务于两个可量化目标：**降低长期维护成本**、**让顶层表现
> 可预测**。本文件对后续所有轮次生效；违反需在本文件追加修订记录并说明
> 理由。与 harness-fusion.md 的关系：那份是「偷什么」，这份是「怎么放」。

## 一、分层铁律

```
┌─ transport 层  api.py / Electron main ──── 只做协议转换，禁止业务逻辑
├─ service 层   core_services + sessions/jobs/spill/sandbox/studio_protocol
├─ domain 层    process.py(引擎) / registry / rules ── 纯决策，不知 HTTP
└─ foundation   paths.py / errors 分类 / 类型单源
```

- 依赖方向只能向下；任何 `domain ← transport` 反向引用即架构缺陷
- **transport 层禁令**：api.py 不允许出现新的业务分支（if 判断业务状态）；
  业务判断下沉到对应 service。端点函数体目标 ≤10 行（解析参数 → 委派 → 包装）

## 二、状态所有权

- 一切可变单例必须挂 `CoreServices` 容器（core_services.py），
  经 create_app 注入；**禁止模块级可变全局**（常量除外）
- 会话型服务（spy/picker/recorder/scrape）以惰性槽位挂在容器上：
  「谁启动谁赋值」，容器不预构造
- 引擎等纯域对象不经容器——它们由调用方按次构造

## 三、路径真相源

- 所有数据目录经 `paths.py` 解析（env `APA_DATA_DIR` 可整体重定向）；
  **禁止在业务代码散写字符串路径** `"data/..."`
- 已收编：sessions / spills / sandbox / processes；新增目录先加进 paths

## 四、错误语义

- RPC 五态是权威分类：method_not_found · invalid_params · not_found ·
  conflict · internal_error（studio_protocol.RpcErrorBody）
- REST 过渡期维持 `HTTPException(status, detail)`，但 detail 必须是
  **中文行动指引**（告诉用户下一步做什么），不得输出裸异常名
- 具体异常类优先于泛化捕获（JobNotFound 是 KeyError 子类的教训已固化为
  测试）

## 五、演进纪律

- 协议/注册表/schema：**只加不改**；破坏性变更必须换名并升版本号
- 生成物（studioProtocol.ts）禁止手改——漂移由门禁拦截
- 平台相关能力（Seatbelt 等）：能力探测 + 显式 skip，不做隐式假设
- 移植外部代码：文件头标注来源与许可（见 NOTICE 规范），并保持
  单一职责——移植时顺手扩大范围视为违规

## 六、测试基座

- 共享夹具进 `tests/conftest.py`（app/client/stub serve_app）
- 集成测试四问：能红吗？确定吗？快吗？可无人值守吗？——四否则改写
- 门禁顺序不变：pytest 全量 → typecheck → build → bundle 断言

## 七、脚本编辑安全（v1.1 新增，事故固化）

- 对同一文件的多段脚本编辑，**执行前必须先落盘快照**
  （`cp file /tmp/backup_<ts>`）；恢复优先用快照而非考古
- 跨段切片替换后立即 `py_compile`/typecheck 验证再继续下一段
- 变量名遮蔽是重灾区：脚本内 import 的函数不得与函数形参同名
  （sessions_dir 事故）

---
*修订记录*
- 2026-08 v1.1 追加 §七 脚本编辑安全（api.py 中段误删事故固化）
- 2026-08 v1 初版（根基加固轮确立：分层/状态/路径/错误/演进/测试六纲）
