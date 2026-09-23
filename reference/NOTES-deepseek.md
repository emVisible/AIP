# NOTES-deepseek — harness-deepseek 萃取（原文已删，68M）

来源：`reference/harness-deepseek`（2026-09-23 删除），仅 `packages/interaction/`
（人工审批/问答/权限）与文档纪律与其余部分（TS agent 框架）无交集，已捨。
只记模式，不记历史。

## 1. One-shot 审批（user-approval）→ 我们的 resolve
- `asked` + `decided` 成对审计记录；grant 只对本次请求有效（allowed-once，无 allow-always）。
- 无 answerer → `unavailable`，**fail closed**（服务自身从不弹窗）。
- 状态机：`allowed-once / rejected / cancelled / unavailable`。
- `ApprovalPolicy` 只有 `ask` / `never`；policy 变更只影响新 session，已有 session pin 住不变。
- **对照缺口（TODO）**：
  - 我们缺 `cancelled` 态（人审超时/撤回目前无语义，pending 会烂尾）。
  - 我们是 fail-open（无引擎 → heuristic 照判），对方是 fail-closed。
    这是故意的产品选择（离线优先），但要在 PROTOCOL 记一笔，不偷换概念。
  - 我们缺 session 级 policy 开关（只有全局阈值）。

## 2. 问答 seam（user-questions）→ 我们的驳回理由
- provider-neutral：`ask({questions:[{id,question,detail?,options?}]})`，intent 只改呈现不改答案字段。
- `custom` 可覆盖选项；无 provider 直接抛 `NO_PROVIDER`（fail closed）。
- **对照缺口（TODO）**：驳回无结构化理由字段（现在只有 outcome），人审 reversal 无法回流训练。

## 3. 权限预设（permission-presets）→ 我们的阈值
- 预设 = 一组 knob 的命名捆绑；选择事件 log-only；`custom` 只能推导不能命名。
- **对照缺口（TODO）**：阈值/引擎顺序全是 env 硬编码，无用户侧预设（一键“严格/均衡/宽松”）。

## 4. 文档纪律（AGENTS.md，检查我们用）
- one-home-per-fact（一个事实只住一处，其余 link）；word budgets（长文档设上限）；
  current-state prose（不写“以前/现在”，变更故事只活在 commit 里）；
  每个包 README 带 Known Limitations。
- **对照自查**：PROTOCOL.md 目前合规；clearance/README.md 偏长，下次动时拆。
