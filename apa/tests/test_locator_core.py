"""locator-core（扩展定位器纯函数库）Node 测试套件的 pytest 门禁。

真实断言在 browser_extension/tests/locator_core.test.mjs；
本文件只负责：node 存在性探测 → subprocess 执行 → 非零退出即失败。
"""
import pathlib
import shutil
import subprocess

import pytest

EXT_DIR = (pathlib.Path(__file__).resolve().parents[1] /
           "packages" / "apa-core" / "apa_core" / "browser_extension")


def test_locator_core_node_suite():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(
        ["node", str(EXT_DIR / "tests" / "locator_core.test.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "assertions passed" in r.stdout
