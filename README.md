# Clearance（放行）— AIP 的产品实现

通用后台审核网关：`内容提交 → Laya 快判 → 自动过 / 自动拦 / 转人工`。

```bash
cd clearance && ./start.sh   # 前端 :5173 · 后端 :8686 · Laya sidecar :8685
```

- 产品文档与运行方式：[`clearance/README.md`](clearance/README.md)
- 协议→实现对照（AIP 思想折叠为一页表）：[`clearance/PROTOCOL.md`](clearance/PROTOCOL.md)
- 只读引用（Laya 上游等，不入构建）：[`reference/README.md`](reference/README.md)

AIP（一句话）：决策引擎与执行器之间最小充分上下文的可靠交互；
本仓库是它的产品实现，概念层已全部转为代码实现，历史版本见 git 记录。
旧 RPA 重资产封存于 `archive/apa-rpa` 分支。
