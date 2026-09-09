"""AFL（Track A P1）编译器测试：语法覆盖＋错误行号＋语义等价。

快模式门禁：只跑本文件＋process 回归子集。
"""
import pytest

from apa_core.dsl import DslError, compile_text, load_afl


def steps_of(src):
    return compile_text(src)["process"]["steps"]


def test_minimal_auto_ids():
    d = compile_text('flow demo\nbrowser.click target=#a\n'
                     'browser.input target=#b value=hi\n')
    p = d["process"]
    assert p["id"] == "demo" and p["mode"] == "process"
    assert [s["id"] for s in p["steps"]] == ["s1", "s2"]
    assert p["steps"][0]["params"] == {"target": "#a"}


def test_full_modifiers_and_types():
    src = ('flow m "T"\n'
           'on event e.x\nmax_actions 50\n'
           '@go browser.click "点" target=#a force=true n=3 r=1.5 '
           'as clicked when {{steps.x == 1}} on_fail -> escalate\n')
    s = steps_of(src)[0]
    assert s["id"] == "go" and s["action"] == "browser.click"
    assert s["params"] == {"target": "#a", "force": True, "n": 3, "r": 1.5}
    assert s["output_as"] == "clicked"
    assert s["condition"] == "{{steps.x == 1}}"
    assert s["on_failure"] == {"goto": "escalate"}


def test_bare_flag_and_quoted_literal():
    s = steps_of('flow m\nbrowser.input target=#a clear\n')[0]
    assert s["params"] == {"target": "#a", "clear": True}
    # 引号里的 on_fail 是字面量，不触发截断
    s = steps_of('flow m\nlog check when status == \'on_fail\'\n')[0]
    assert s["condition"] == "status == 'on_fail'"


def test_for_while_ask_run_log():
    src = ('flow m\n'
           '@loop for oid in {{event.ids}} as items:\n'
           '    context.set key="k" value={{oid}}\n'
           '@poll while steps.poll.last.status != \'done\' max_iter=20:\n'
           '    api.http.get url="https://x/api"\n'
           '@d1 ask "能批吗？" with steps.order, event '
           'options=[approve, reject] as decision\n'
           '@r1 run child in={"oid": "{{oid}}"} as ch\n'
           '@l1 log "done"\n')
    p = compile_text(src)["process"]
    by = {s["id"]: s for s in p["steps"]}
    assert by["loop"]["type"] == "foreach"
    assert by["loop"]["params"] == {"source": "{{event.ids}}",
                                   "item_var": "oid"}
    assert by["loop"]["output_as"] == "items"
    assert by["loop"]["body_steps"][0]["action"] == "context.set"
    assert by["poll"]["type"] == "while"
    assert by["poll"]["params"]["max_iterations"] == 20
    assert by["d1"]["type"] == "ai_decision"
    assert by["d1"]["params"]["context"][0] == "能批吗？"
    assert by["d1"]["params"]["available_actions"] == ["approve", "reject"]
    assert by["r1"]["params"] == {"process_id": "child",
                                 "input": {"oid": "{{oid}}"}}
    assert by["l1"] == {"id": "l1", "type": "log",
                       "params": {"message": "done"}}


def test_script_escape():
    src = ('flow m\n'
           '@clean script python timeout=30 as rows:\n'
           '    """\n'
           '    rows = {{steps.e.rows}}\n'
           '    # 注释原样保留\n'
           '    return [r for r in rows]\n'
           '    """\n')
    s = steps_of(src)[0]
    assert s["action"] == "code.python"
    assert s["params"]["timeout_s"] == 30
    assert "rows = {{steps.e.rows}}" in s["params"]["code"]
    assert "# 注释原样保留" in s["params"]["code"]
    assert "timeout_s" not in steps_of(
        'flow m\n@s script python as x:\n    """\n    return 1\n    """\n'
    )[0]["params"]


def test_handler_single_step():
    d = compile_text('flow m\nbrowser.click target=#a on_fail -> quota\n'
                     'handler quota:\n'
                     '    log "超限"\n')
    assert d["process"]["error_handlers"]["quota"]["type"] == "log"


def test_golden_data_scrape_report_equivalence():
    from pathlib import Path
    afl = load_afl(str(Path(__file__).parent /
                       "fixtures_dsl" / "data_scrape_report.afl"))
    # P2：YAML 原件已删，此测试锁定 .afl 编译语义（字段级）
    assert afl.process_id == "data_scrape_report"
    assert [s.id for s in afl.steps] == ["open_page", "scrape_table",
                                        "big_orders", "report"]
    by = {s.id: s for s in afl.steps}
    assert by["scrape_table"].params["columns"] == {
        "order_id": ".order-id", "customer": ".customer",
        "amount": ".amount"}
    assert by["scrape_table"].params["max_rows"] == 200
    assert by["big_orders"].params == {"column": "amount", "op": ">",
                                      "value": 1000}
    assert by["report"].params["body_type"] == "html"


def test_golden_batch_approve_equivalence():
    from pathlib import Path
    afl = load_afl(str(Path(__file__).parent /
                       "fixtures_dsl" / "batch_approve.afl"))
    # P2：YAML 原件已删，此测试锁定 .afl 编译语义（字段级）
    assert afl.process_id == "batch_approve"
    assert [s.id for s in afl.steps] == ["loop_orders", "done"]
    a_loop = afl.steps[0]
    assert a_loop.type == "foreach"
    assert a_loop.params["item_var"] == "oid"
    assert a_loop.params["source"] == "{{event.order_ids}}"
    assert afl.steps[1].action == "email.send"


def test_load_afl_validates_like_yaml():
    from pathlib import Path
    p = load_afl(str(Path(__file__).parent /
                     "fixtures_dsl" / "batch_approve.afl"))
    assert p.process_id == "batch_approve"
    assert p.max_actions == 100


@pytest.mark.parametrize("src,msg", [
    ("", "空"),
    ("browser.click target=#a\n", "flow <id>"),
    ("flow m\n  browser.click target=#a\n", "顶层语句不能缩进"),
    ("flow m\nbrowser.click target=#a\n\tsub\n", "Tab"),
    ("flow m\n@l for o in {{e}}:\n  context.set key=\"k\"\n", "4 空格"),
    ("flow m\nclick target=#a\n", "全名"),
    ("flow m\n@a browser.click target=#a on_fail -> no_such\n", "不存在"),
    ("flow m\n@a browser.click target=#a\n@a log x\n", "重复"),
    ("flow m\n@s script js as x:\n    \"\"\"\n    1\n    \"\"\"\n", "仅支持 python"),
    ("flow m\n@w while x > 1:\n    log y\n", "max_iter"),
    ("flow m\nbrowser.click target=#a\nhandler h:\n    log x\n    log y\n",
     "恰为一个步骤"),
    ("flow m\nbrowser.click target=#a when\n", "缺表达式"),
    ("flow m\nbrowser.click target=#a on_fail x\n", "on_fail 写法"),
    ("flow m\nbrowser.click target=#a as x as y\n", "as 重复"),
    ("flow m\nbrowser.click target=#a on_fail -> s9\nbrowser.click target=#b\n",
     "不存在"),
])
def test_errors_with_lines(src, msg):
    with pytest.raises(DslError) as e:
        compile_text(src)
    assert msg in str(e.value)
    if src.strip():
        assert "第" in str(e.value) and "行" in str(e.value)
    # 空文件无行号：只有消息断言（首个 assert 已覆盖）


def test_spec_ok_blocks_compile_and_validate():
    """docs/afl-spec.md 里所有 afl-ok 块必须编译＋过引擎校验。
    文档与实现单一真相：文档例烂了，测试先红。"""
    import re
    from pathlib import Path
    from apa_core.process import build_process
    src = (Path(__file__).parent.parent / "docs" / "afl-spec.md"
           ).read_text(encoding="utf-8")
    blocks = re.findall(r"```afl-ok\n(.*?)```", src, re.DOTALL)
    assert len(blocks) >= 2
    for b in blocks:
        build_process(compile_text(b))


def test_bare_id_dwim():
    # 裸 id（次词动词位）与 @ 显式同义
    a = steps_of('flow m\ns1 browser.click target=#a\n')[0]
    b = steps_of('flow m\n@s1 browser.click target=#a\n')[0]
    assert a["id"] == b["id"] == "s1"
    assert a == b
    # 动词位首词不是 id：无点非关键字作动词仍报错
    with pytest.raises(DslError):
        compile_text('flow m\nclick target=#a\n')


def test_script_colon_optional():
    a = steps_of('flow m\n@s script python as x:\n    """\n    return 1\n    """\n')[0]
    b = steps_of('flow m\n@s script python as x\n    """\n    return 1\n    """\n')[0]
    assert a["params"]["code"] == b["params"]["code"] == "return 1"
