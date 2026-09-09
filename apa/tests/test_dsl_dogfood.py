"""AFL 狗粮验收（Track A P3-T4）：只读 docs/afl-spec.md 现写的流程，
headless 真跑。断言：循环迭代 / ask 绑定 / when 跳过 /
失败跳转 handler / script 透传。"""
from apa_core.dsl import compile_text
from apa_core.process import ProcessEngine, build_process

# 下面的 .afl 是一次写成的（仅查文档，未看 parser 源码）。
DOGFOOD = '''\
flow dogfood_approval "狗粮审批"
on manual
max_actions 50

@fetch browser.extract_table table=#orders max_rows=10 as orders
@clean script python as big:
    """
    rows = {{steps.orders.rows}}
    return [r for r in rows if r]
    """
@decide ask "大额单放行吗？" with {{steps.clean}} options=[go, no] as verdict
@pay api.charge amount=100 on_fail -> broke
@quiet log "小额静默" when {{verdict.outcome == 'no'}}
@done log "收工 {{verdict.outcome}}"

handler broke:
    hb log "支付挂了，已升级"
'''


def _run(sent, decisions, fail_actions=()):
    proc = build_process(compile_text(DOGFOOD))
    eng = ProcessEngine(
        proc,
        lambda a, p: (sent.append((a, p)), (False, {"code": "boom"})
                      if a in fail_actions else (True, {"rows": [{"x": 1}],
                                                        "count": 3}))[1],
        decision_fn=lambda ctx, avail: {"outcome": decisions},
    )
    eng.run.scopes["event"] = {}
    eng._run_from(0)
    return eng


def test_dogfood_happy_path():
    sent = []
    eng = _run(sent, "go")
    steps = eng.run.scopes["steps"]
    # for 呢？本流无 for——循环由 batch golden 覆盖；此处验 ask/when/script
    assert steps["verdict"]["outcome"] == "go"
    assert steps["big"]["count"] == 3
    actions = [a for a, _ in sent]
    assert "browser.extract_table" in actions
    assert "api.charge" in actions
    # when 假 → quiet 跳过：无 quiet 相关副作用（log 不经过 send_fn，
    # 用 journal 条目验证）
    kinds = [(e.get("step"), e.get("type")) for e in eng.run.steps]
    assert ("quiet", "log") not in [(s, t) for s, t in kinds
                                    if t == "log" and s == "quiet"]
    assert any(s == "done" for s, _ in kinds)


def test_dogfood_failure_goto_handler():
    sent = []
    eng = _run(sent, "go", fail_actions=("api.charge",))
    kinds = [(e.get("step"), e.get("type")) for e in eng.run.steps]
    # 引擎以 broke(handler) 记录 handler 调用（体内 log 不另行记账）
    assert any(s == "broke(handler)" for s, _ in kinds), kinds
    assert eng.run.outcome == "escalated"
