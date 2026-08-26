"""apa-executors: 外部 MCP 工具桥执行器（H5 二期 · 反向接入）。

两个稳定动作（避免动态动作名爆炸，工具发现数据经参数流动）：
  mcp.tools_list  {server}                     → 外部服务器全部工具
  mcp.tool_call   {server, tool, arguments}    → 调用外部工具取回结果

配置真相源：env ``APA_MCP_SERVERS``（JSON：名称→{command,timeout_s?}）。
未配置时动作返回明确错误而非静默失败。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, Tuple

import json
import threading
from typing import Any, Dict, Tuple


_lock = threading.Lock()
_pool: "McpPool | None" = None


def _get_pool():
    # 懒导入（对齐 api_executor→vault 先例，避免包级循环）
    # 仅首次构建；测试可直接替换模块属性 me._pool 注入
    from apa_core.mcp_client import McpPool, servers_from_env

    global _pool
    with _lock:
        if _pool is None:
            _pool = McpPool(servers_from_env())
        return _pool


class McpBridgeExecutor:
    """域前缀 mcp. 的桥执行器。"""

    def __init__(self, name: str, session: str) -> None:
        self.name = name
        self.session = session

    def _execute_action(self, action: str,
                        params: dict) -> Tuple[bool, dict]:
        handler = {
            "mcp.tools_list": self._tools_list,
            "mcp.tool_call": self._tool_call,
        }.get(action)
        if handler is None:
            return False, {"code": "action_not_supported_by_executor",
                           "detail": action}
        try:
            return True, handler(params or {})
        except Exception as e:  # noqa: BLE001  # McpClientError 等统一桥错误
            return False, {"code": "mcp_error", "error": str(e)}

    # ---- 动作实现 --------------------------------------------------------------

    def _tools_list(self, p: Dict[str, Any]) -> Dict[str, Any]:
        server = str(p.get("server", ""))
        cli = _get_pool().get(server)
        tools = cli.list_tools()
        return {"server": server, "count": len(tools), "tools": tools}

    def _tool_call(self, p: Dict[str, Any]) -> Dict[str, Any]:
        server = str(p.get("server", ""))
        tool = str(p.get("tool", ""))
        if not server or not tool:
            return {"code": "missing_param",
                    "detail": "server/tool"}
        cli = _get_pool().get(server)
        result = cli.call_tool(tool, p.get("arguments") or {})
        text_parts = [c.get("text", "")
                      for c in result.get("content", [])
                      if isinstance(c, dict) and c.get("type") == "text"]
        return {
            "server": server, "tool": tool,
            "is_error": bool(result.get("isError")),
            "result_text": "\n".join(t for t in text_parts)[:8000],
        }

    # ---- 目录元数据（设计器/意图层消费） ---------------------------------------

    @staticmethod
    def configured() -> bool:
        """env 是否声明了至少一个外部 MCP 服务器。"""
        import os

        return bool(os.environ.get("APA_MCP_SERVERS", "").strip())

    @staticmethod
    def describe_actions() -> List[Dict[str, Any]]:
        """registry 片段生成器输入：两稳定动作的目录元数据。"""
        return [
            {"name": "mcp.tools_list", "executor_domain": "mcp",
             "label_cn": "列出外部 MCP 工具",
             "description": "枚举已配置外部 MCP 服务器的全部工具"
                            "（APA_MCP_SERVERS 配置）",
             "params": {"type": "object",
                        "required": ["server"],
                        "properties": {"server": {"type": "string"}}},
             "risk": "L0", "idempotency": "required"},
            {"name": "mcp.tool_call", "executor_domain": "mcp",
             "label_cn": "调用外部 MCP 工具",
             "description": "调用外部 MCP 服务器的指定工具并取回文本结果",
             "params": {"type": "object",
                        "required": ["server", "tool"],
                        "properties": {
                            "server": {"type": "string"},
                            "tool": {"type": "string"},
                            "arguments": {"type": "object"}},
                        },
             "risk": "L2", "idempotency": "none"},
        ]
