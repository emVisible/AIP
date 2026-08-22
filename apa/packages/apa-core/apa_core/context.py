"""apa-core: APAContextStore（设计文档 §4.2 CoD 规范）。

在 AIP ContextStore 之上增加：
  · ref 格式强制 `ctx_{session_id}_{name}`（跨 Session 越权防护，附录 B.3）
  · 字段级 ACL（CoD-2：只能取声明/已存的字段，禁止 fields:["*"]）
  · snapshot/invalidate（审计需要快照权限）
  · 事件 data 4KB 上限（CoD-1，校验在 gateway 层做）
ContextStore 由 Executor 持有，不进入协议传输（CoD-3）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from aip import Clock, ContextStore

REF_RE = re.compile(r"^ctx_([A-Za-z0-9_]+)_([A-Za-z0-9_]+)$")


class ContextRefError(ValueError):
    pass


class APAContextStore(ContextStore):
    def __init__(self, session_id: str, *, clock: Optional[Clock] = None) -> None:
        super().__init__(clock=clock)
        self.session_id = session_id
        # 前缀判定：ref 必须以前缀开头，杜绝 session_id 含下划线时的歧义
        self.ref_prefix = f"ctx_{session_id}_"
        self._acls: Dict[str, Dict[str, List[str]]] = {}  # ref -> {field: [principal]}
        self._allowed: Dict[str, List[str]] = {}  # ref -> [field,...]

    # --- ref 管理 ------------------------------------------------------------
    @staticmethod
    def make_ref(session_id: str, name: str) -> str:
        return f"ctx_{session_id}_{name}"

    def split_ref(self, ref: str) -> str:
        """校验 ref 属于本 Session，返回 name 部分。"""
        if not ref.startswith(self.ref_prefix):
            raise ContextRefError(
                f"ref {ref!r} does not belong to session {self.session_id!r}")
        return ref[len(self.ref_prefix):]

    @classmethod
    def parse_ref(cls, ref: str) -> Tuple[str, str]:
        """尽力解析为 (session, name)。若无法可靠分割则抛错。"""
        m = REF_RE.match(ref)
        if not m:
            raise ContextRefError(f"ref {ref!r} must match ctx_{{session}}_{{name}}")
        return m.group(1), m.group(2)

    def _check_ref_session(self, ref: str) -> None:
        """Gateway 在 context.get 时必须校验 ref 前缀与当前 session_id 匹配。"""
        self.split_ref(ref)

    def put(
        self,
        ref: str,
        data: Dict[str, Any],
        *,
        ttl_ms: Optional[int] = None,
        acl: Optional[Dict[str, List[str]]] = None,
        allowed_fields: Optional[List[str]] = None,
    ) -> str:
        """存数据。acl 为 {field: [principal,...]} 的字段级访问控制。

        allowed_fields 声明"哪些字段可被 context.get 按需获取"（CoD-2 的
        声明来源）。未声明字段仅在拥有权限时可通过 get 获取。
        """
        self._check_ref_session(ref)
        super().put(ref, data, ttl_ms=ttl_ms)
        self._acls[ref] = dict(acl or {})
        self._allowed[ref] = list(allowed_fields or list(data.keys()))
        return ref

    def get(
        self, ref: str, fields: Optional[List[str]] = None, principal: str = "system"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        self._check_ref_session(ref)
        if fields == ["*"]:
            return None, "context.wildcard_forbidden"  # CoD-2
        data, err = super().get(ref, fields=None)
        if err:
            return None, err
        acl = self._acls.get(ref, {})
        declared = self._allowed.get(ref)  # CoD-2：只能取声明的字段
        result: Dict[str, Any] = {}
        requested = fields if fields is not None else (declared or list(data.keys()))
        for f in requested:
            if f not in data:
                continue
            if declared is not None and f not in declared:
                continue
            if acl.get(f) and principal not in acl[f]:
                continue
            result[f] = data[f]
        return result, None

    def snapshot(self, ref: str) -> Optional[Dict[str, Any]]:
        """审计用快照（需审计权限，由调用方保证）。"""
        data, err = super().get(ref, fields=None)
        if err:
            return None
        return dict(data)

    def invalidate(self, ref: str) -> None:
        self.delete(ref)
        self._acls.pop(ref, None)
        self._allowed.pop(ref, None)

    def list_refs(self) -> List[str]:
        return list(self._objects.keys())

    # --- 上下文记录（供决策引擎使用，不传输）--------------------------------
    def describe(self, ref: str) -> dict:
        obj = self._objects.get(ref)
        if obj is None:
            return {"ref": ref, "exists": False}
        return {
            "ref": ref,
            "exists": True,
            "version": obj["version"],
            "fields": sorted(self._allowed.get(ref, [])),
            "expires": obj["expires"],
        }