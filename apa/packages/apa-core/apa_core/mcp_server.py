"""apa-core: 最小 MCP stdio 服务（H5 · harness-fusion 资产 #7 出口侧）。

把 Action Registry（186+ 动作）暴露为标准 MCP server：
任一 MCP 客户端（Claude/其他代理）可 tools/list 发现、tools/call 调用。
协议子集自实现（initialize / notifications/initialized / tools/list /
tools/call / ping），零新依赖；设计参照 codex mcp-server 思路，
反向接入（外部 MCP 工具→APA 动作）留二期。

安全门禁：risk ≥ L2 的动作默认拒绝（返回审批指引文案）；
env ``APA_MCP_ALLOW_HIGH_RISK=1`` 显式放行。执行复用
``launcher.run_process`` 迷你流程管线——沙箱/spill 语义自动继承。

工具命名：动作名点号 → 双下划线（MCP 工具名字符集限制），
description 首行保留原始动作名供回溯。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "apa-mcp", "version": "0.1.0"}

REFUSAL_TMPL = ("动作 {name} 风险等级 {risk}，默认拒绝经 MCP 暴露调用。"
                "如确认，请在启动端设置 APA_MCP_ALLOW_HIGH_RISK=1 "
                "并确保人工审批策略生效。")

# JSON-RPC 错误码（MCP 沿用）
ERR_PARSE = -32700
ERR_METHOD = -32601
ERR_INVALID = -32602
ERR_INTERNAL = -32603


def sanitize_tool_name(action: str) -> str:
    return action.replace(".", "__")


def _domain_tokens(registry) -> Dict[str, set]:
    """registry 驱动：executor_domain → 该域全部动作首段集合。
    （CompositeExecutor 按动作名首段前缀路由，string.* 等数据族
    的 executor_domain 是 data，必须以令牌集合显式登记。）"""
    toks: Dict[str, set] = {}
    for name in registry.names():
        e = registry.get(name)
        d = getattr(e, "executor_domain", "") or ""
        if not d:
            continue
        toks.setdefault(d, set()).add(name.split(".")[0])
    return toks


def _default_executors_builder(registry) -> Callable[[str], List]:
    """返回「会话名 → 本地执行器组合」工厂（缺失域静默降级）。"""
    tokens = _domain_tokens(registry)

    def build(session: str) -> List[Tuple[tuple, Any]]:
        mods: List[Tuple[tuple, Any]] = []
        suffix = session[-6:] if session else "mcsrv"

        def add(domains: tuple, cls_path: str):
            try:
                mod_path, cls_name = cls_path.rsplit(".", 1)
                import importlib
                cls = getattr(importlib.import_module(mod_path), cls_name)
                mods.append((domains, cls(f"bot_{suffix}", session)))
            except Exception:  # noqa: BLE001
                pass

        def take(domain: str) -> tuple:
            toks = sorted(tokens.get(domain, set()))
            out = list(toks)
            # 执行器自身可能还声明了额外前缀能力（如 core.delay 在 data）
            return tuple(out) if out else (domain,)

        add(take("data"), "apa_executors.data_executor.DataExecutor")
        add(take("browser"), "apa_executors.browser_executor.BrowserExecutor")
        if sys.platform == "darwin":
            add(take("desktop"), "apa_executors.ax_executor.AXExecutor")
            add(take("ocr"), "apa_executors.ocr_executor.OCRExecutor")
        return mods

    return build


class McpServer:
    """注册表 → MCP 工具出口。``handle`` 为纯分发器便于测试。"""

    def __init__(self, registry: Any,
                 executors_builder: Optional[Callable[[], List]] = None,
                 *, allow_high_risk: bool = False,
                 run_process_fn: Optional[Callable] = None) -> None:
        self.registry = registry
        self.allow_high_risk = allow_high_risk or bool(
            os.environ.get("APA_MCP_ALLOW_HIGH_RISK") == "1")
        if executors_builder is None:
            executors_builder = _default_executors_builder(registry)
        self._executors_builder = executors_builder
        self._mods_cache: Optional[List] = None
        self._run_process = run_process_fn or self._run_mini_process  # 兼容旧注入
        self._by_tool: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for action in sorted(registry.names()):
            entry = registry.get(action)
            tool = sanitize_tool_name(action)
            self._by_tool[tool] = (action, entry or {})

    # ---- 元数据 -------------------------------------------------------------

    def tools_list(self) -> List[Dict[str, Any]]:
        tools = []
        for tool, (action, entry) in sorted(self._by_tool.items()):
            schema = entry.params if isinstance(entry.params, dict) else None
            if not isinstance(schema, dict) or schema.get("type") != "object":
                schema = {"type": "object",
                          "properties": {},
                          "additionalProperties": True}
            desc = f"[{action} · {entry.risk}] {entry.label_cn}".strip()
            tools.append({"name": tool,
                          "description": desc,
                          "inputSchema": schema})
        return tools

    # ---- 执行 ---------------------------------------------------------------

    def _run_mini_process(self, action: str,
                          arguments: Dict[str, Any]) -> Dict[str, Any]:
        import tempfile

        from .launcher import run_process

        steps = [{"id": "mcp_call", "action": action,
                  "params": arguments}]
        proc = {"process": {"id": f"mcp_{sanitize_tool_name(action)}",
                            "mode": "process",
                            "trigger": {"type": "manual"},
                            "max_actions": 3,
                            "steps": steps}}
        with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", delete=False,
                encoding="utf-8") as fh:
            json.dump(proc, fh, ensure_ascii=False)
            holder = fh.name
        return run_process(
            holder, "", {},
            executors=self._executors_builder("s_mcp"),
            session_prefix="s_mcp",
            timeout_s=60.0,
        )

    def tools_call(self, tool: str,
                   arguments: Dict[str, Any]) -> Dict[str, Any]:
        pair = self._by_tool.get(tool)
        if pair is None:
            raise KeyError(f"unknown tool: {tool}")
        action, entry = pair
        risk = str(getattr(entry, "risk", "") or "")
        if risk in ("L2", "L3") and not self.allow_high_risk:
            return {"content": [{"type": "text",
                                 "text": REFUSAL_TMPL.format(
                                     name=action, risk=risk)}],
                    "isError": True}
        # v1 直调模式：定位覆盖该动作首段的执行器模块，直接调用
        # _execute_action —— 返回真实数据；经引擎审计的调用走设计器/试运行
        mod = self._find_executor_module(action)
        if mod is None:
            return {"content": [{"type": "text",
                                 "text": f"no local executor for "
                                         f"{action}"}],
                    "isError": True}
        ok, data = mod._execute_action(action, arguments or {})
        text = json.dumps({"ok": ok, "data": data},
                          ensure_ascii=False, default=str)[:8000]
        return {"content": [{"type": "text", "text": text}],
                "isError": not ok}

    def _executors(self) -> List[Tuple[tuple, Any]]:
        if self._mods_cache is None:
            self._mods_cache = self._executors_builder("s_mcp")
        return self._mods_cache

    def _find_executor_module(self, action: str):
        prefix = action.split(".")[0]
        for tokens, mod in self._executors():
            if prefix in tokens:
                if hasattr(mod, "_execute_action"):
                    return mod
        return None

    # ---- 分发 -----------------------------------------------------------------

    def handle(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """JSON-RPC 分发。notification（无 id）返回 None。"""
        rid = req.get("id")
        method = str(req.get("method", ""))
        params = req.get("params") or {}

        def resp(result: Any) -> Dict[str, Any]:
            return {"jsonrpc": "2.0", "id": rid, "result": result}

        def err(code: int, message: str) -> Dict[str, Any]:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": code, "message": message}}

        if method == "initialize":
            return resp({"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": {"tools": {}},
                         "serverInfo": SERVER_INFO})
        if method == "ping":
            return resp({})
        if method == "tools/list":
            return resp({"tools": self.tools_list()})
        if method == "tools/call":
            name = str(params.get("name", ""))
            args = params.get("arguments") or {}
            try:
                return resp(self.tools_call(name, args))
            except KeyError as e:
                return err(ERR_INVALID, str(e))
            except Exception as e:  # noqa: BLE001
                return err(ERR_INTERNAL, f"{type(e).__name__}: {e}")
        if rid is None:
            return None                      # notification：不回包
        return err(ERR_METHOD, f"unknown method: {method}")

    # ---- stdio 主循环 -----------------------------------------------------------

    def serve_stdio(self, infile=None, outfile=None) -> int:
        inp = infile or sys.stdin
        out = outfile or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError:
                payload = {"jsonrpc": "2.0", "id": None,
                           "error": {"code": ERR_PARSE,
                                     "message": "parse error"}}
                out.write(json.dumps(payload) + "\n")
                out.flush()
                continue
            resp = self.handle(req)
            if resp is not None:
                out.write(json.dumps(resp, ensure_ascii=False) + "\n")
                out.flush()
        return 0


def build_default_server(registries: Optional[List[str]] = None,
                         *, allow_high_risk: bool = False) -> McpServer:
    """CLI 入口：按路径加载 registry 并构建服务（缺省用内置全集）。"""
    from .launcher import default_registries
    from .registry import load_registries

    paths = registries or [str(p) for p in default_registries()]
    reg = load_registries(*paths)
    return McpServer(reg, allow_high_risk=allow_high_risk)
