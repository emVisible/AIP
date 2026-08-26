"""apa-core: 最小 MCP stdio 客户端（H5 二期 · 反向接入）。

与 mcp_server.py 同源对称：握手（initialize + notifications/initialized）
→ tools/list → tools/call。零新依赖；读超时经 select 防御坏服务器挂死
（POSIX；Windows 降级为阻塞读）。
"""
from __future__ import annotations

import json
import os
import select
import subprocess
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2024-11-05"


class McpClientError(RuntimeError):
    pass


class McpClient:
    """一个外部 MCP stdio 服务器连接。非线程安全（单会话使用）。"""

    def __init__(self, name: str, command: List[str],
                 *, timeout_s: float = 30.0) -> None:
        self.name = name
        self._timeout = timeout_s
        try:
            self._proc = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
        except FileNotFoundError as e:
            raise McpClientError(
                f"MCP[{name}] 启动失败: {e}") from e
        self._next_id = 1

    # ---- 低层 ------------------------------------------------------------------

    def _readline_timeout(self) -> str:
        fd = self._proc.stdout.fileno()   # type: ignore[union-attr]
        deadline = self._timeout
        # select 轮询（秒级粒度足够）
        remaining = deadline
        while remaining > 0:
            ready, _, _ = select.select([fd], [], [], min(0.5, remaining))
            if ready:
                line = self._proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise McpClientError(
                        f"MCP[{self.name}] 服务器提前退出")
                return line
            remaining -= 0.5
        raise McpClientError(
            f"MCP[{self.name}] 响应超时（{self._timeout}s）")

    def request(self, method: str,
                params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rid = self._next_id
        self._next_id += 1
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid,
                               "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)
        while True:
            resp = json.loads(self._readline_timeout())
            if resp.get("id") == rid:
                if "error" in resp:
                    err = resp["error"]
                    raise McpClientError(
                        f"MCP[{self.name}] {method}: "
                        f"{err.get('code')} {err.get('message')}")
                return resp.get("result") or {}

    def notify(self, method: str,
               params: Optional[Dict[str, Any]] = None) -> None:
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def _write(self, obj: Dict[str, Any]) -> None:
        if self._proc.poll() is not None:
            raise McpClientError(f"MCP[{self.name}] 进程已退出")
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    # ---- 会话 ------------------------------------------------------------------

    def handshake(self) -> Dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "apa-bridge", "version": "0.1.0"},
        })
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self.request("tools/list", {})
        return list(result.get("tools") or [])

    def call_tool(self, name: str,
                  arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("tools/call",
                            {"name": name, "arguments": arguments})

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass


# ---- 配置与多服务器管理 ---------------------------------------------------------

def servers_from_env(env_var: str = "APA_MCP_SERVERS"
                     ) -> Dict[str, Dict[str, Any]]:
    """env JSON：{"name": {"command": [...], "timeout_s"?: float}}。
    未设置/坏 JSON 返回空表（桥执行器据此优雅报错）。"""
    raw = os.environ.get(env_var, "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class McpPool:
    """命名客户端池：惰性握手、进程内复用（executor 级缓存）。"""

    def __init__(self, config: Dict[str, Dict[str, Any]]) -> None:
        self._config = config
        self._clients: Dict[str, McpClient] = {}
        self._lock = __import__("threading").Lock()

    def names(self) -> List[str]:
        return sorted(self._config)

    def get(self, name: str) -> McpClient:
        with self._lock:
            cli = self._clients.get(name)
        if cli is not None:
            return cli
        cfg = self._config.get(name)
        if not cfg or not cfg.get("command"):
            raise McpClientError(
                f"MCP 服务器「{name}」未配置（APA_MCP_SERVERS）")
        cli = McpClient(name, list(cfg["command"]),
                        timeout_s=float(cfg.get("timeout_s", 30)))
        cli.handshake()
        with self._lock:
            self._clients[name] = cli
        return cli

    def close_all(self) -> None:
        for cli in self._clients.values():
            cli.close()
        self._clients.clear()
