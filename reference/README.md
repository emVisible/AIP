# reference — 只读引用项目（不入产品构建，不进 git）

本目录只放 Clearance 依赖思想但不属于产品的外部项目。
一律只读使用，禁止产品代码 import 此处源码（Laya 例外：通过 pip 安装正式包）。

| 目录 | 是什么 | 上游 / 更新方式 |
|---|---|---|
| `laya/` | AI 底座：多语言非自回归 System-1 决策模型（`choice/score/noul`，33ms 单次前向）。Clearance 的决策引擎以它为目标实现 | 上游：`github.com/NandhaKishorM/laya`（嵌套独立 git）。更新：`git -C reference/laya pull`；产品依赖走 `pip install laya`，不直引源码 |
| `harness-deepseek/` | DeepSeek Harness v0.1（模型无关决策引擎参考，旧 APA 设计文档引用过） | 纯本地目录，无独立 git。以只读参考存在 |
| `harness-codex/` | OpenAI Codex 上游仓库（agent/harness 实现参考） | 上游可重拉（嵌套独立 git）。更新：`git -C reference/harness-codex pull` |

旧 RPA 重资产（`apa/`、设计文档、旧 plans）**不在此目录**，
只活在 `archive/apa-rpa` 分支 + `archive/apa-rpa-2026-09-23` tag。如需考古：

```bash
git checkout archive/apa-rpa
```
