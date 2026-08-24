"""apa-core: Action Registry engine（设计文档 §9）。

Registry 是 idempotency / risk / timeout / retries 的唯一来源（C3），
禁止在 action 消息中携带这些属性。条目从 YAML 加载，params 用 JSONSchema 校验。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

RISK_LEVELS = ("L0", "L1", "L2", "L3", "L4")
IDEMPOTENCY_VALUES = ("required", "optional", "none")


class RegistryError(Exception):
    pass


@dataclass
class RegistryEntry:
    name: str
    description: str = ""
    label_cn: str = ""
    domain: str = ""
    params: Optional[dict] = None
    idempotency: str = "none"
    timeout_ms: int = 0
    retries: int = 0
    risk: str = "L0"
    requires_approval_at: Optional[str] = None
    audit_fields: List[str] = field(default_factory=list)
    audit_mask_fields: List[str] = field(default_factory=list)
    expect: Optional[str] = None
    allowed_principals: Optional[List[str]] = None
    executor_domain: str = "any"
    deprecated: bool = False

    def validate_params(self, params: Any) -> List[str]:
        """校验 params 是否满足 schema。返回错误列表（空 = 通过）。"""
        if self.params is None:
            return []
        try:
            from jsonschema import Draft7Validator, ValidationError
        except ImportError:
            return []
        if not isinstance(params, dict):
            return ["params must be an object"]
        validator = Draft7Validator(schema=self.params)
        errors = [e.message for e in validator.iter_errors(params)]
        # CoD-2：禁止 fields: ["*"]（仅 context.get 相关，schema 层已拦截，
        # 这里再加一层硬校验，防止 schema 被误改）
        if self.name == "context.get" and params.get("fields") == ["*"]:
            errors.append("fields ['*'] is forbidden by CoD-2")
        return errors


class ActionRegistry:
    def __init__(self) -> None:
        self._entries: Dict[str, RegistryEntry] = {}

    # --- 构建 ---------------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: str | Path) -> "ActionRegistry":
        if yaml is None:
            raise RegistryError("PyYAML is required: pip install pyyaml")
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RegistryError(f"registry {path} must be a mapping of name -> entry")
        reg = cls()
        for name, raw in data.items():
            reg._register(name, raw)
        return reg

    @classmethod
    def from_dict(cls, data: dict) -> "ActionRegistry":
        reg = cls()
        for name, raw in data.items():
            reg._register(name, raw)
        return reg

    def _register(self, name: str, raw: dict) -> None:
        if not isinstance(raw, dict):
            raise RegistryError(f"entry {name} must be a mapping")
        idempotency = raw.get("idempotency", "none")
        risk = raw.get("risk", "L0")
        if idempotency not in IDEMPOTENCY_VALUES:
            raise RegistryError(f"{name}: invalid idempotency {idempotency!r}")
        if risk not in RISK_LEVELS:
            raise RegistryError(f"{name}: invalid risk {risk!r}")
        if raw.get("retries", 0) and idempotency != "required":
            raise RegistryError(
                f"{name}: retries>0 requires idempotency=required (C3)")
        entry = RegistryEntry(
            name=name,
            description=raw.get("description", ""),
            label_cn=raw.get("label_cn", ""),
            domain=raw.get("domain", name.split(".", 1)[0]),
            params=raw.get("params"),
            idempotency=idempotency,
            timeout_ms=raw.get("timeout_ms", 0),
            retries=raw.get("retries", 0),
            risk=risk,
            requires_approval_at=raw.get("requires_approval_at"),
            audit_fields=list(raw.get("audit_fields", [])),
            audit_mask_fields=list(raw.get("audit_mask_fields", [])),
            expect=raw.get("expect"),
            allowed_principals=raw.get("allowed_principals"),
            executor_domain=raw.get("executor_domain", "any"),
            deprecated=raw.get("deprecated", False),
        )
        self._entries[name] = entry

    # --- 查询 ---------------------------------------------------------------
    def get(self, name: str) -> Optional[RegistryEntry]:
        return self._entries.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def all(self) -> Dict[str, RegistryEntry]:
        return dict(self._entries)

    def names(self) -> List[str]:
        return sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def as_dict(self) -> dict:
        """序列化（审计/调试用）。idempotency/risk 不进入消息，只进注册表。"""
        out = {}
        for name, e in self._entries.items():
            out[name] = {
                "domain": e.domain,
                "executor_domain": e.executor_domain,
                "idempotency": e.idempotency,
                "risk": e.risk,
                "timeout_ms": e.timeout_ms,
                "retries": e.retries,
                "requires_approval_at": e.requires_approval_at,
                "audit_fields": e.audit_fields,
                "audit_mask_fields": e.audit_mask_fields,
            }
        return out


def load_registries(*paths: str | Path) -> ActionRegistry:
    """合并多个 YAML registry 文件为一个 Registry（后者覆盖前者同名条目）。"""
    merged: Dict[str, dict] = {}
    for p in paths:
        if yaml is None:
            raise RegistryError("PyYAML is required")
        data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RegistryError(f"registry {p} must be a mapping")
        merged.update(data)
    return ActionRegistry.from_dict(merged)


def dump_json(registry: ActionRegistry, **kw: Any) -> str:
    return json.dumps(registry.as_dict(), ensure_ascii=False, **kw)