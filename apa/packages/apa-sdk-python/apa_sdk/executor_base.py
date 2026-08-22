"""apa-sdk: AIPExecutor 基类（设计文档 §5.2）。

协议层职责（基类处理，子类禁止重写）：
  · AIP Peer 管理（seq / cursor / session）
  · duplicate 检测 / gap 处理
  · 幂等性守卫（executed_action_ids）
  · accepted 先行回复（AIP §4.5）
  · 错误分类（业务失败 → result.failed / 前置条件失败 → rejected / 协议异常 → error）
  · context.get / context.update 内置实现（CoD）

业务层职责（子类实现）：
  · _execute_action(name, params) → (success: bool, data: dict)
  · start_observation() ← 启动感知循环，持续 send_event

注意：POC 采用同步实现（配合 aip 同步传输与 playwright.sync_api），
async 变体仅需把 _dispatch_action 改为 await 即可，结构相同。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from aip import AIPPeer

from apa_core.context import APAContextStore

MAX_EVENT_DATA_BYTES = 4096  # CoD-1


class ExecutorPreconditionError(Exception):
    """前置条件失败 → result rejected（AIP §4.4）。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code = code


class AIPExecutor:
    def __init__(
        self,
        source: str,
        session_id: str,
        transport=None,
        *,
        context_store: Optional[APAContextStore] = None,
    ) -> None:
        self.peer = AIPPeer(source=source, session_id=session_id, transport=transport)
        self.context_store = context_store or APAContextStore(session_id)
        self._executed: Dict[str, Tuple[str, str]] = {}  # action_id -> (status, result_id)

    # --- inbound ---------------------------------------------------------------
    def on_message(self, raw: dict) -> None:
        cls, msg = self.peer.handle(raw)
        if cls == "duplicate":
            if msg.type == "action":
                self._replay_outcome(msg.id)
            return
        if cls != "accept":
            return  # stale/gap 由 Gateway 处理
        if msg.type == "action":
            self._dispatch_action(msg)

    # --- action 分发 ------------------------------------------------------------
    def _dispatch_action(self, msg) -> None:
        action_id = msg.id
        name = msg.payload.get("name", "")
        params = msg.payload.get("params", {}) or {}

        # 幂等性守卫（AIP I2）
        if action_id in self._executed:
            status, original_id = self._executed[action_id]
            self.peer.send_result(status, in_reply_to=action_id,
                                  duplicate=True, original_result_id=original_id)
            return

        # 长操作先回 accepted（AIP §4.5）
        self.peer.send_result("accepted", in_reply_to=action_id)

        # 内置：context 域（CoD）
        if name == "context.get":
            self._do_context_get(action_id, params)
            return
        if name == "context.update":
            self._do_context_update(action_id, params)
            return

        try:
            success, data = self._execute_action(name, params)
            status = "ok" if success else "failed"
        except ExecutorPreconditionError as e:
            result_id = self.peer.send_result(
                "rejected", in_reply_to=action_id, code=e.code, message=str(e)).id
            self._executed[action_id] = ("rejected", result_id)
            return
        except Exception as e:  # 协议层之外：视为业务内部错误
            status, data = "failed", {"code": "internal_error", "detail": str(e)}

        result_id = self.peer.send_result(
            status, in_reply_to=action_id,
            data=data if status == "ok" else None,
            code=data.get("code") if status != "ok" else None,
        ).id
        self._executed[action_id] = (status, result_id)

    def _do_context_get(self, action_id: str, params: dict) -> None:
        try:
            data, err = self.context_store.get(
                params.get("ref", ""), params.get("fields"),
                principal=self.peer.source,
            )
        except Exception as e:  # ref 格式错误等
            result_id = self.peer.send_result(
                "failed", in_reply_to=action_id, code="context.ref_invalid",
                message=str(e)).id
            self._executed[action_id] = ("failed", result_id)
            return
        if err:
            result_id = self.peer.send_result(
                "failed", in_reply_to=action_id, code=err).id
            self._executed[action_id] = ("failed", result_id)
            return
        result_id = self.peer.send_result(
            "ok", in_reply_to=action_id,
            data={"ref": params["ref"], "data": data}).id
        self._executed[action_id] = ("ok", result_id)

    def _do_context_update(self, action_id: str, params: dict) -> None:
        ref = params.get("ref", "")
        fields = params.get("fields", {})
        try:
            current, err = self.context_store.get(ref, None, principal=self.peer.source)
            if err:
                raise ExecutorPreconditionError(err)
            current.update(fields)
            self.context_store.put(ref, current)
        except Exception as e:
            result_id = self.peer.send_result(
                "failed", in_reply_to=action_id,
                code=getattr(e, "code", "context.update_failed"), message=str(e)).id
            self._executed[action_id] = ("failed", result_id)
            return
        result_id = self.peer.send_result(
            "ok", in_reply_to=action_id, data={"ref": ref}).id
        self._executed[action_id] = ("ok", result_id)

    def _replay_outcome(self, action_id: str) -> None:
        if action_id in self._executed:
            status, original_id = self._executed[action_id]
            self.peer.send_result(status, in_reply_to=action_id,
                                  duplicate=True, original_result_id=original_id)

    # --- 事件发射 ----------------------------------------------------------------
    def emit(self, name: str, data: Optional[dict] = None) -> None:
        """发送语义事件。data 超 4KB 拒绝（CoD-1，开发期即报错）。"""
        if data is not None:
            size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            if size > MAX_EVENT_DATA_BYTES:
                raise ValueError(
                    f"event {name!r} data is {size}B, exceeds CoD-1 limit "
                    f"{MAX_EVENT_DATA_BYTES}B — put bulk data in ContextStore and "
                    "send a reference instead (C5)")
        self.peer.send_event(name, data=data)

    def put_context(self, name: str, data: dict, **kw) -> str:
        """便捷：按格式 ctx_{session}_{name} 存入 ContextStore，返回 ref。"""
        ref = self.context_store.make_ref(self.peer.session_id, name)
        return self.context_store.put(ref, data, **kw)

    # --- 业务层（子类实现） --------------------------------------------------------
    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        raise NotImplementedError

    def start_observation(self) -> None:
        """启动感知循环，通过 self.peer.send_event() 持续发出语义事件。"""
        raise NotImplementedError