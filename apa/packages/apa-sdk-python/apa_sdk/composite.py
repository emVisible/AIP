"""apa-sdk: 复合执行器 —— 单协议身份，多领域能力模块。

设计文档 §10.3 的单流简化：一个 Session 侧一个 AIP 身份（peer/序列/
幂等守卫/ContextStore 共享），动作按前缀路由到注册的能力模块。
能力模块只需实现 `_execute_action(name, params) -> (bool, dict)`
（即 AIPExecutor 子类实例，或任何提供该签名的对象）。

    router = CompositeExecutor("bot_01", session_id)
    router.register(("doc",), DocumentExecutor(...))
    router.register(("api", "erp"), APIExecutor(...))
"""
from __future__ import annotations

from typing import List, Tuple

from .executor_base import AIPExecutor


class CompositeExecutor(AIPExecutor):
    def __init__(self, source: str, session_id: str, transport=None, **kw) -> None:
        super().__init__(source, session_id, transport, **kw)
        self._routes: List[Tuple[tuple, object]] = []

    def register(self, prefixes: tuple, module) -> "CompositeExecutor":
        """注册能力模块。prefixes 如 ("doc",) 或 ("api", "erp")。"""
        self._routes.append((tuple(prefixes), module))
        # 共享 ContextStore 与协议身份：模块内 context.* 引用与 ref 生成
        # 必须落在同一存储/会话上（CoD-3 / C5）
        if hasattr(module, "context_store"):
            module.context_store = self.context_store
        if hasattr(module, "peer"):
            module.peer = self.peer
        return self

    def start_observation(self) -> None:
        for _, module in self._routes:
            if hasattr(module, "start_observation"):
                module.start_observation()

    def _execute_action(self, name: str, params: dict):
        for prefixes, module in self._routes:
            if any(name == p or name.startswith(p + ".") for p in prefixes):
                return module._execute_action(name, params)
        return False, {"code": "action_not_supported_by_executor"}