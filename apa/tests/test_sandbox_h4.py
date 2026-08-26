"""H4 Seatbelt 沙箱测试（docs/harness-fusion.md §5 H4）。

单测全平台跑；集成用例 darwin-only（显式跳过，平台无关纪律）。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from apa_executors.sandbox import SEATBELT_PATH, build_command, is_available


# ---- 单元 ----

@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS")
def test_build_command_shape():
    argv = build_command(["/bin/echo", "hi"])
    assert argv[0] == SEATBELT_PATH and argv[1] == "-f"
    profile = argv[2]
    text = open(profile).read()
    assert "(deny default)" in text
    assert "allow network" not in text, "网络必须保持默认拒绝"
    assert f'(subpath "{Path.cwd()}")' in text


def test_non_darwin_raises():
    if sys.platform == "darwin":
        pytest.skip("仅非 darwin 分支")
    with pytest.raises(RuntimeError):
        build_command(["/bin/echo"])


# ---- 集成（真实 sandbox-exec） ----

@pytest.mark.skipif(not is_available(), reason="sandbox-exec unavailable")
def test_sandboxed_python_runs_and_can_write_workspace(tmp_path):
    target = tmp_path / "inside.txt"
    code = (f"open({str(target)!r}, 'w').write('ok'); "
            "print('done')")
    argv = build_command([sys.executable, "-c", code],
                         workspace=tmp_path)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert target.read_text() == "ok"


@pytest.mark.skipif(not is_available(), reason="sandbox-exec unavailable")
def test_sandbox_blocks_write_outside_workspace(tmp_path):
    # 越界点：工作区（tmp_path）之外的用户级目录
    home_violation = tmp_path.parent / "apa_sbx_escape_test.txt"
    code = f"open({str(home_violation)!r}, 'w').write('no')"
    argv = build_command([sys.executable, "-c", code],
                         workspace=tmp_path)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "越界写必须被沙箱拒绝"
    assert not home_violation.exists()


# ---- 执行器级 ----

@pytest.mark.skipif(not is_available(), reason="sandbox-exec unavailable")
def test_code_python_executor_sandboxed_hello(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # 工作区=临时目录，写 cwd 合法
    from apa_executors.data_executor import DataExecutor

    ex = DataExecutor("bot_t", "s_h4")
    ok, data = ex._code_python({"code": "print('hello-sandbox')",
                                "timeout_s": 20})
    assert ok and data["exit_code"] == 0
    assert "hello-sandbox" in data["stdout"]
    assert data.get("sandboxed") is True
