# AFL v1 语言规范（APA Flow Language，`.afl`）

> 真相源：`packages/apa-core/apa_core/dsl/`（parser＋compiler）。
> 本文档是其人类/AI 可读投影；冲突时以代码为准并回改本文。
> 定位：L3 编排真相源 → 编译向下到 ProcessDef → 引擎（`process.py`）一字不动。

## 0. 铁律（四条）

1. **一行一步**，无行必有义；`#` 整行注释；空行随意；行尾 `\` 续行。
2. **关键字小写英文**；自由文本（标题/消息）任意语言；v1 无中文别名。
3. **表达式零发明**：`when` 原样透传引擎 Python 受限 eval（比较/布尔/
   点路径/字面量/算术），`{{…}}` 包裹与否皆可。
4. **动作写全名**（`browser.click` 不省——`click` 在多域真实歧义）。

## 1. 文件结构

```afl
flow <id> ["标题"]        # 必需第一行，id 字母数字下划线

on event <名> | on manual  # 缺省=manual
max_actions <正整数>       # 缺省 100（引擎默认）
timeout_minutes <正整数>   # 缺省 60（引擎默认）

<步骤…>

[handler <名>:            # 错误处理命名块（见 §7）
    <恰一个步骤>]
```

## 2. 步骤行

```
[id] <动词> ["标题"] [key=value …] [as 名] [when 表达式] [on_fail -> 目标]
```

- id 可省略（编译器按序编号 `s1…`）；裸写 `s1 click …` 即 id（次词是
  动词位时首词自动判 id）；`@s1` 显式写法同义。显式 id 推荐（goto 稳定）。
- 修饰子句**固定顺序**：参数 → `as` → `when` → `on_fail`，违序编译错。
- `as 名`：输出绑定（`output_as`）；缺省＝步骤 id。读：`{{<名>.<字段>}}`。
- `when 表达式`：条件跳过（非分支——条件假则**跳过**本步）。
- `on_fail -> T`：失败跳转，`T` ＝ 顶层步骤 id / handler 名 / `escalate`。
  悬空目标**编译期报错**（YAML 只在运行时炸）。
- `title` 纯元数据（未来视图用），编译丢弃。

## 3. 值语法

| 写法 | 含义 | 例 |
|---|---|---|
| `k=v`（裸词） | `true/false`→bool；数字→数；其余字符串 | `clear`（裸 flag＝True）、`assignee=manager` |
| `k="…"` | 字符串（可含空格/`{{}}`） | `target=#submit`、`body="共 {{n}} 笔"` |
| `k=[a, b]` | 列表 | `options=[approve, reject]` |
| `k={"a": 1}` | JSON 字典 | `in={"oid": "{{oid}}"}` 也可（宽容解析） |
| `{{path}}` | 模板引用，原样透传统计引擎渲染 | `value={{oid}}`、`{{steps.e.rows}}` |
| `null` | 空值（YAML null 对等体，round-trip 用） | `x=null` |

保留键：`expect`（v1 未开放，写了就报）；禁 C3 键（`idempotency`/`risk`）。

## 4. 循环

```afl
[id] for <var> in <ref> [as 名] [on_fail -> T]:
    <缩进体（4 空格，一次一级，可嵌套）>

[id] while <表达式> max_iter=<N> [as 名] [on_fail -> T]:
    <缩进体>
```

- `for` → `type=foreach`（`source`/`item_var`＋`body_steps`）。
- `while` → `type=while`；`max_iter` **强制**（引擎防死循环要求）。
- `repeat <次数> [from <起>] [as <var>]:` → `type=for_times`
  （次数可为 `{{ref}}`；`as` 绑循环变量，缺省引擎默认 `item`）。
- `forever [max_iter=N] [as <var>]:` → `type=loop.infinite`。
- `break [when …]`／`continue [when …]` → 循环控制信号；须在循环体内
  （顶层写直接编译错）；不支持 `on_fail`（无失败语义，出现即错）。
- 体内 `{{var}}` 为当轮项；`tab` 禁用，缩进跳层报错。

## 5. 问 AI（`ask`）

```afl
[id] ask "问题" [with r1, r2] options=[a, b] [as 名]
```

→ `type=ai_decision`。**问题文本进 `context` 首位**（引擎只读
`context`，问题丢了等于白问）；`with` 追加上下文引用；
`options` 必填（可空列表＝引擎默认）；`uncertain` 时走
`escalate`（引擎行为）。

## 6. 子流程（`run`）与日志（`log`）

```afl
[id] run <流程id> [in={...}] [as 名]      # → type=sub_process
[id] log "消息" [as/when/on_fail]          # → type=log
```

## 7. 错误处理

```afl
@pay api.charge amount=100 on_fail -> quota_exceeded

handler quota_exceeded:      # 体必须恰一个步骤
    escalate_target notify message="额度用尽" as _
```

`on_fail` 行尾 `->` 两侧空格可有可无；目标不存在编译错。

## 8. 兜底脚本（语言的一等公民）

```afl
[id] script python [timeout=<秒>] [nosandbox] [as 名]:
    """
    <原文收录，去公共缩进；# 是 Python 注释>
    """
```

→ `action=code.python`（subprocess＋Seatbelt 沙箱＋审计）。
`script js` 及其他语言：parser 放行、**编译期诚实报错**（引擎尚无
对应 executor，不画饼）。
`timeout` 缺省不填（引擎默认）；`nosandbox` 仅本地调试用。

## 9. 错误信息

所有错误带行号（`第N行: … > 源码行`），文件级错误（空文件）除外。
常见：`块关键字须为…`／`修饰子句顺序…`／`跳转目标不存在`／
`handler 体必须恰一个步骤`／`while 须带 max_iter`／`禁用 Tab`。

## 10. 完整例（`afl-ok` 块全部机检：编译＋引擎校验）

```afl-ok
flow demo "最小可运行"
on manual

@hi log "hello"
@run1 browser.click "提交" target=#submit on_fail -> esc_handler
@q ask "放行吗？" with {{steps.run1}} options=[yes, no] as verdict
@go browser.navigate url="https://example.com" when {{verdict.outcome == 'yes'}}

handler esc_handler:
    h1 log "已升级"
```

```afl-ok
flow poll_demo "轮询＋脚本清洗"
on manual
max_actions 30

@poll while steps.poll.last.status != 'done' max_iter=5 as poll:
    api.http.get url="https://example.com/api/status"

@clean script python as rows:
    """
    rows = {{steps.poll.last.items}}
    return [r for r in rows if r]
    """
@show log "取到 {{rows}}"
```

> 约定：` ```afl ` 为示意片段（含占位符，不可编译）；
> ` ```afl-ok ` 为完整可运行例，CI 逐块编译＋`build_process` 校验。

## 11. 打印机（规范形式，D1）

`print_text`：process-dict → 规范 `.afl`。用途：画布回写、YAML 迁移。
往返保证：`parse(print(parse(x))) ≡ parse(x)`（dict 恒等，测试锁定）。

- 头默认值恒显式（`max_actions`/`timeout_minutes` 写全值，所见即所运行）。
- 参数按字母序；`target` 置首；`code.python` 恒用 `script` 糖。
- 有损清单（宁可报错不伪造）：`title` 不在 dict 里，不打印；
  未知 `type` 直接报错；老式 `body_action`（无 `body_steps`）就地升级
  为单步体（语义等价，引擎同路径）。
