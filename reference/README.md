# reference — 只读引用（不入产品构建，不进 git）

本目录只放 Clearance 依赖思想但不属于产品的外部项。
一律只读使用，禁止产品代码 import 此处源码（Laya 例外：通过 pip/git-pin 安装正式包）。

| 项 | 是什么 | 上游 / 更新方式 |
|---|---|---|
| `laya/` | AI 底座：多语言非自回归 System-1 决策模型。sidecar 依赖 pin 到 `010bace`，与此副本一致 | 上游：`github.com/NandhaKishorM/laya`（嵌套独立 git）。更新：`git -C reference/laya pull` |
| `NOTES-deepseek.md` | harness-deepseek 萃取：one-shot 审批、问答 seam、权限预设、文档纪律（原文 68M 已删） | 萃取快照，不更新；源仓与本产品无交集 |

已删除（无价值，不恢复）：
- `harness-codex/`（647M，从未读过，零重叠）：需用时 `git clone` 上游。
- `harness-deepseek/` 原文（68M）：有价值部分见上表萃取版。

旧 RPA 重资产（`apa/`、设计文档、旧 plans）**不在此目录**，
只活在 `archive/apa-rpa` 分支 + `archive/apa-rpa-2026-09-23` tag。如需考古：

```bash
git checkout archive/apa-rpa
```
