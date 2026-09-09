# APA × AIP 内核一致性 verdict（C 阶段）

> 跑法：`apa/tests/test_aip_conformance.py` 把 repo-root
> `conformance/tests/*.json` 行为夹具逐条跑在 `APAGateway` 上
> （断言语义与 `conformance/harness.py` 对齐；registry/policy/clock
> 做 APA-surface 适配，见文件头注释）。
> Schema 层（`conformance/run.py`）与实现无关，常绿，不在此复述。

## Verdict：22/22（21 behavior PASS＋E5 SKIP）

E5 需 WebSocket 绑定测试，不在 Python 适配器内（与 reference 同口径 SKIP）。

## 验证中抓到的 4 个真问题（已修，测试锁定）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| F1 | D2 resume 空转：`task.started` 等合法内核事件被拒收，转发缓冲为空 | 事件命名空间强制 3 段＋缺 `task`/`button` 域；fixtures 全是 2 段通用名 | 正则放宽到 ≥2 段；补两域。拒收通用自动化事件是互操作 bug 不是严格 |
| F2 | D4 心跳 `pong` 缺失（AttributeError） | reference 有，APA 没抄过来 | 3 行镜像（心跳不占 seq） |
| F3 | K3 凭据事件无拒绝 | `_scan` 只在 action 路径；event 路径裸奔 | event 入口先扫（与 reference 同序）；同时记 `I10`＋`C4` 两码 |
| F4 | K4 首条 action 即审批 → `INITIALIZING→SUSPENDED` 非法崩溃 | `suspend_for_human` 假设会话已起步 | 起步后再挂（两步都合状态图） |

## 有意保留的偏离（非 bug，记账）

1. **result/error 不做凭据扫描**：返回凭据值是合法行为，扫了是误杀。
   reference 全扫——APA 在此比 reference 更对，不是更错。
2. **拒绝形态**：APA 走终端 result（`status=rejected＋code`）而非 error
   消息——fixtures 的 `status`/`outcome` 断言全部通过，`errors` 类不断言
   拒绝路径（K3 除外，已对齐）。
3. **事件命名保留形状约束**（小写/点式/禁用祈使段）：内核不管，APA 管——
   这是 profile 个性，不是互操作障碍（fixtures 全过即证）。
