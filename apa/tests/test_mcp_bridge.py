"""H5 二期测试：外部 MCP 工具桥（狗粮闭环——自家 server 作外部端）。"""
import json
import subprocess
import sys

import pytest

from apa_core.mcp_client import McpClient, McpClientError, servers_from_env
from apa_executors.mcp_executor import McpBridgeExecutor


# ---- env 配置解析 ----

def test_servers_from_env_variants(monkeypatch):
    monkeypatch.delenv("APA_MCP_SERVERS", raising=False)
    assert servers_from_env() == {}
    monkeypatch.setenv("APA_MCP_SERVERS", "{broken")
    assert servers_from_env() == {}
    monkeypatch.setenv("APA_MCP_SERVERS",
                       '{"local": {"command": ["x"], "timeout_s": 5}}')
    cfg = servers_from_env()
    assert cfg["local"]["command"] == ["x"]


# ---- 客户端 ----

def test_client_missing_command_raises():
    with pytest.raises(McpClientError, match="启动失败"):
        McpClient("nope", ["/definitely/not/existing"])


@pytest.fixture(scope="module")
def ext_server():
    """自家 mcp-serve 充当外部服务器（狗粮闭环）。"""
    proc = subprocess.Popen(
        [sys.executable, "-m", "apa_core.cli", "mcp-serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, cwd=".",
    )
    yield proc
    proc.terminate()


def test_bridge_lists_and_calls_through_external_server(ext_server):
    monkey_src = json.dumps({
        "self": {"command": [sys.executable, "-m",
                             "apa_core.cli", "mcp-serve"]}})
    ex = McpBridgeExecutor("bot_t", "s_h5b")
    # 注入配置与池（绕过进程 env 全局污染）
    from apa_core.mcp_client import McpPool

    pool = McpPool({"self": {
        "command": [sys.executable, "-m", "apa_core.cli", "mcp-serve"]}})

    class _Bridged(McpBridgeExecutor):
        pass

    bridged = _Bridged("bot_t", "s_h5b")
    bridged.__class__ = McpBridgeExecutor  # 保持类型
    # 用 monkeypatch 方式替换模块级池更干净：
    import apa_executors.mcp_executor as me

    orig = me._pool
    me._pool = pool
    try:
        ok, listing = ex._execute_action(
            "mcp.tools_list", {"server": "self"})
        assert ok and listing["count"] >= 180
        names = {t["name"] for t in listing["tools"]}
        assert "string__upper" in names

        ok, out = ex._execute_action("mcp.tool_call", {
            "server": "self", "tool": "string__upper",
            "arguments": {"text": "bridge"}})
        assert ok and "BRIDGE" in out["result_text"]
    finally:
        me._pool = orig


def test_unconfigured_server_clear_error():
    import os

    import apa_executors.mcp_executor as me

    orig = me._pool
    me._pool = None
    old_env = os.environ.get("APA_MCP_SERVERS")
    os.environ.pop("APA_MCP_SERVERS", None)
    try:
        ex = McpBridgeExecutor("bot_t", "s")
        ok, err = ex._execute_action("mcp.tools_list",
                                     {"server": "ghost"})
        assert ok is False and "未配置" in err["error"]
    finally:
        me._pool = orig
        if old_env is not None:
            os.environ["APA_MCP_SERVERS"] = old_env


def test_registry_contains_bridge_actions():
    import yaml

    core = yaml.safe_load(open("registries/core.yaml"))
    assert core["mcp.tools_list"]["risk"] == "L0"
    assert core["mcp.tool_call"]["risk"] == "L2"   # 外部副作用默认审批级
