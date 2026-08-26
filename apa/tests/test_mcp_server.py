"""H5 MCP 出口测试：命名消毒 / schema 透传 / 高风险门禁 / stdio e2e。"""
import json
import subprocess
import sys

import pytest

from apa_core.mcp_server import McpServer, build_default_server


@pytest.fixture(scope="module")
def server():
    return build_default_server()


def test_tools_list_covers_registry(server):
    tools = server.tools_list()
    assert len(tools) >= 180
    names = {t["name"] for t in tools}
    assert "browser__navigate" in names
    assert "string__upper" in names


def test_tool_metadata_sanitized_and_schema_passthrough(server):
    t = next(t for t in server.tools_list()
             if t["name"] == "browser__navigate")
    assert t["description"].startswith("[browser.navigate")
    assert "打开网页" in t["description"]
    assert t["inputSchema"]["type"] == "object"
    assert "url" in t["inputSchema"]["properties"]


def test_high_risk_refused_by_default(server):
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "api__http__post",
                                  "arguments": {"url": "http://x"}}})
    payload = r["result"]
    assert payload["isError"] is True
    assert "APA_MCP_ALLOW_HIGH_RISK" in payload["content"][0]["text"]


def test_allow_high_risk_flag_proceeds_to_execution():
    reg = build_default_server().registry
    from types import SimpleNamespace

    fake_mod = SimpleNamespace(
        _execute_action=lambda name, params: (True, {"status": 200}))
    srv = McpServer(reg,
                    executors_builder=lambda session: [(("api",), fake_mod)],
                    allow_high_risk=True,
                    run_process_fn=lambda action, args: {})
    r = srv.tools_call("api__http__post", {"url": "http://x"})
    assert r["isError"] is False
    assert '"status": 200' in r["content"][0]["text"]


def test_unknown_tool_invalid_params(server):
    r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "nope"}})
    assert r["error"]["code"] == -32602


def test_notification_yields_no_response(server):
    assert server.handle({"jsonrpc": "2.0",
                          "method": "notifications/initialized"}) is None


# ---- stdio 子进程端到端 ----

def _send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _recv(proc):
    while True:
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("server closed unexpectedly")
        line = line.strip()
        if line:
            return json.loads(line)


@pytest.mark.skipif(sys.platform == "win32", reason="stdio pipe 差异")
def test_stdio_end_to_end_list_and_call(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "apa_core.cli", "mcp-serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, cwd=".",
    )
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {}})
        init = _recv(proc)
        assert init["result"]["protocolVersion"] == "2024-11-05"

        # notification：无 id，服务端不回包
        _send(proc, {"jsonrpc": "2.0",
                     "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _recv(proc)["result"]["tools"]
        assert len(tools) >= 180

        _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "string__upper",
                                "arguments": {"text": "apa-mcp"}}})
        out = _recv(proc)["result"]
        assert out["isError"] is False
        assert "APA-MCP" in out["content"][0]["text"]
    finally:
        proc.terminate()
