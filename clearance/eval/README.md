# eval — 阈值调优与样本验收

## 样本格式（JSONL，一行一条）

```json
{"kind": "article", "title": "…", "body": "…", "expected": "approve"}
```

- `expected` 三选一：`approve`（应自动过）/ `reject`（应自动拦）/ `review`（应转人工）。
- 脱敏要求：去掉真实姓名、电话、身份证、密码原文，保留语义类型
  （如把真手机号写成 `138xxxx0000`，真密码写成 `密码是xxxxxx`——注意：
  含“密码”字样会触发 heuristic 的 sensitive 规则，这正是要测的行为）。

## 运行

```bash
cd clearance
python3 -m eval.sweep eval/samples_example.jsonl   # 自带 8 条合成样本，验证链路
python3 -m eval.sweep /path/to/your_samples.jsonl  # 你的真实样本
```

输出每档阈值的准确率 / 自动率 / 转人工率 / 自动判错数，并推荐一档阈值。
推荐逻辑：自动判错最少优先，其次准确率——自动放错（approve 了不该过的）
比转人工贵得多，所以宁可 human_rate 高，不可 auto_err > 0。

## 温度拟合（calibrate）

```bash
python3 -m eval.calibrate --samples /path/to/your.jsonl --out eval/calibration.json
```

要求 sidecar 在跑；`expected==review` 的行自动跳过（弃权类不可标定）。
`category` 需行内 `labels.category` 真值才会拟合。样本少（单边）的 qid
不写入，运行时按 T=1 出厂值。sidecar 按文件 mtime 热重载，无需重启。
**合成样本只验链路，不提交 calibration.json**——拟合只吃真实样本。

## 把样本给我

直接发文件或粘贴 JSONL，每类（过/拦/转人工）各 10 条以上最有价值。
拿到后我做三件事：① sweep 定阈值 ② 挑难例进 `tests/` 做回归 ③ 攒 Laya 微调种子。
