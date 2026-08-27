"""apa-core: 设置子系统（H7 · 文件+UI 双写，架构宪法 §二/§三）。

分层真相源（低→高优先）：
    内置 defaults → 用户层 ~/.apa/config.yaml → 项目层 ./apa.config.yaml
    → env 兼容映射（遗留变量，标记 owned）→ 运行时 override(active_profile)

密钥治理（C4 对齐）：配置树中**不存在** api_key 字段——只有
`api_key_ref` 引用规格 {"vault": name} / {"env": VAR}，运行时经
VaultManager 解析。结构化脱敏：想泄也无处可写。

双写：settings.update(patch) 校验后热应用并原子写回用户层；
env-owned 路径拒绝写回（含指引信息）。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from .paths import user_config_dir, project_config_path

__all__ = ["Settings", "SettingsManager", "deep_merge", "LEGACY_ENV_MAP"]

log = logging.getLogger("apa.settings")


# ---- 模型（单源：注册进 studio codegen 的模型清单见 studio_protocol 引用） ----

class LlmSettings(BaseModel):
    provider: str = "deepseek"           # deepseek | openai_compat
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    auth_spec: Dict[str, str] = Field(
        default_factory=lambda: {"env": "DEEPSEEK_API_KEY"},
        description='机密引用 {"vault":name}|{"env":VAR}，禁止明文')
    temperature: float = 0.0
    max_tokens: Optional[int] = None


class ApprovalSettings(BaseModel):
    require_human_at_risk: str = "L3"    # L3/L4 → REQUIRE_HUMAN


class SandboxSettings(BaseModel):
    seatbelt_enabled: bool = True
    mcp_allow_high_risk: bool = False


class McpServerEntry(BaseModel):
    command: List[str]
    timeout_s: float = 30.0


class McpSettings(BaseModel):
    servers: Dict[str, McpServerEntry] = Field(default_factory=dict)


class DataSettings(BaseModel):
    root: str = "data"


class SurfacesSettings(BaseModel):
    chrome: bool = True
    daemon: bool = False


class Settings(BaseModel):
    version: int = 1
    llm: LlmSettings = Field(default_factory=LlmSettings)
    approval: ApprovalSettings = Field(default_factory=ApprovalSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    surfaces: SurfacesSettings = Field(default_factory=SurfacesSettings)
    profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    active_profile: Optional[str] = None


# ---- 遗留 env 兼容映射（值存在时标记路径为 env-owned） --------------------------

LEGACY_ENV_MAP: Dict[str, str] = {
    "APA_LLM_MODEL": "llm.model",
    "DEEPSEEK_MODEL": "llm.model",
    "APA_LLM_BASE_URL": "llm.base_url",
    "DEEPSEEK_BASE_URL": "llm.base_url",
    "APA_MCP_SERVERS": "mcp.servers",
    "APA_MCP_ALLOW_HIGH_RISK": "sandbox.mcp_allow_high_risk",
    "APA_DATA_DIR": "data.root",
}


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """dict 递归合并。返回新对象。

    语义：overlay 标量覆盖；子 dict 深入；**overlay 值为 None → 删除该键**
    （列表/映射条目的移除表达方式，与 jq *="empty" 惯例对齐）。
    """
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _apply_env_compat(data: Dict[str, Any],
                      ) -> tuple[Dict[str, Any], List[str]]:
    """遗留 env 变量注入 + 标记 owned 路径。"""
    owned: List[str] = []
    for env_name, path in LEGACY_ENV_MAP.items():
        raw = os.environ.get(env_name)
        if not raw:
            continue
        if path == "mcp.servers":
            try:
                val = json.loads(raw)
            except ValueError:
                log.warning("env %s 非 JSON，忽略", env_name)
                continue
        elif path == "sandbox.mcp_allow_high_risk":
            val = raw.lower() in ("1", "true", "yes")
        else:
            val = raw
        parts = path.split(".")
        node = data
        for seg in parts[:-1]:
            node = node.setdefault(seg, {})
        node[parts[-1]] = val
        owned.append(path)
    return data, owned


def _set_path(data: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for seg in parts[:-1]:
        node = node.setdefault(seg, {})
    node[parts[-1]] = value


def _apply_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    active = (data.get("active_profile"))
    prof = (data.get("profiles") or {}).get(str(active))
    if isinstance(prof, dict) and prof:
        # profile 只覆盖其声明的 section
        for section, patch in prof.items():
            base = data.get(section)
            data[section] = (deep_merge(base, patch)
                             if isinstance(base, dict) else patch)
    return data


class SettingsManager:
    """分层加载 + 热更新 + 用户层原子写回。线程安全。"""

    def __init__(self, *,
                 user_path: Optional[Path] = None,
                 project_path: Optional[Path] = None,
                 active_profile: Optional[str] = None) -> None:
        self.user_path = Path(user_path) if user_path \
            else user_config_dir() / "config.yaml"
        self.project_path = Path(project_path) if project_path \
            else project_config_path()
        self._lock = threading.RLock()
        self._env_owned: List[str] = []
        self._settings = self._load(active_profile)

    # ---- 加载 -----------------------------------------------------------------

    def _load(self, active_profile: Optional[str] = None) -> Settings:
        merged: Dict[str, Any] = {}
        for label, path in (("user", self.user_path),
                            ("project", self.project_path)):
            layer = _read_yaml(path, label)
            if layer:
                merged = deep_merge(merged, layer)
        merged, owned = _apply_env_compat(merged)
        self._env_owned = owned  # reload 持（可重入）锁时安全
        if active_profile:
            merged["active_profile"] = active_profile
        merged = _apply_profile(merged)
        return Settings.model_validate(merged)

    def reload(self, active_profile: Optional[str] = None) -> Settings:
        with self._lock:
            self._settings = self._load(active_profile)
            return self._settings

    # ---- 读（结构化脱敏：树中本无机文字段） -------------------------------------

    @property
    def current(self) -> Settings:
        return self._settings

    def get(self) -> Dict[str, Any]:
        """redacted 视图。env-owned 路径显式标注来源。"""
        data = json.loads(self._settings.model_dump_json())
        for path in self._env_owned:
            _mark_owned(data, path)
        return data

    def env_owned_paths(self) -> List[str]:
        return list(self._env_owned)

    # ---- 写（双写：内存热应用 + 原子写回用户层） --------------------------------

    def update(self, patch: Dict[str, Any],
               *, write_back: bool = True) -> Settings:
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch 必须为非空 JSON 对象")
        schema_full = Settings.model_json_schema(
            ref_template="#/$defs/{model}")
        rejected = _unknown_keys(patch, schema_full)
        if rejected:
            raise ValueError(f"未知/禁写键: {', '.join(sorted(rejected))}")
        for path in self.env_owned_paths():
            if _path_in_patch(patch, path):
                raise ValueError(
                    f"{path} 由环境变量 {self._env_var_of(path)} 管理，"
                    "请修改环境变量而非配置文件")
        merged = deep_merge(json.loads(self._settings.model_dump_json()),
                            patch)
        new_settings = Settings.model_validate(merged)
        with self._lock:
            self._settings = new_settings
            if write_back:
                payload = json.loads(new_settings.model_dump_json())
                for path in self.env_owned_paths():
                    _del_path(payload, path)
                _atomic_write_yaml(self.user_path, payload)
        return new_settings

    @staticmethod
    def _env_var_of(path: str) -> str:
        for env_name, owned in LEGACY_ENV_MAP.items():
            if owned == path:
                return env_name
        return path


def _path_in_patch(patch: Dict[str, Any], dotted: str) -> bool:
    node: Any = patch
    for seg in dotted.split("."):
        if not isinstance(node, dict) or seg not in node:
            return False
        node = node[seg]
    return True


def _del_path(data: Dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    node = data
    for seg in parts[:-1]:
        node = node.get(seg)
        if not isinstance(node, dict):
            return
    node.pop(parts[-1], None)


def _mark_owned(data: Dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    node = data
    for seg in parts[:-1]:
        nxt = node.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            node[seg] = nxt
        node = nxt
    last = parts[-1]
    prev = node.get(last)
    node[last] = {"value": prev,
                  "_source": f"env:{dotted}"} if not isinstance(prev, dict) \
        else prev


def _unknown_keys(patch: Dict[str, Any], schema: Dict[str, Any],
                  prefix: str = "") -> List[str]:
    """按 JSON Schema 找出 patch 中未声明/禁写的键。

    分支优先级（经验教训）：
      1. additionalProperties.$ref（Dict[str, Model] 映射逐项校验）
      2. $ref（对象模型递归；anyOf 解包可选）
      3. 其余按类型收敛为 unknown
    """
    props = schema.get("properties") or {}
    defs: Dict[str, Any] = (schema.get("$defs") or {})

    def resolve_ref(prop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ref = prop.get("$ref")
        if ref:
            return defs.get(ref.split("/")[-1])
        for variant in prop.get("anyOf", []):
            if "$ref" in variant:
                return defs.get(variant["$ref"].split("/")[-1])
        return None

    def first_type(prop: Dict[str, Any]) -> Optional[str]:
        if prop.get("type"):
            return prop["type"]
        for variant in prop.get("anyOf", []):
            if variant.get("type"):
                return variant["type"]
        return None

    def is_model_object(prop: Dict[str, Any]) -> bool:
        return bool(resolve_ref(prop)) or first_type(prop) == "object"

    bad: List[str] = []

    def walk(value: Any, sch: Dict[str, Any], prefix: str) -> None:
        # ① 映射模型：Dict[str, Model] —— 逐值进入模型 schema
        addl = sch.get("additionalProperties")
        if isinstance(addl, dict) and "$ref" in addl:
            inner_name = addl["$ref"].split("/")[-1]
            inner = defs.get(inner_name)
            if inner and isinstance(value, dict):
                for vk, vv in value.items():
                    walk(vv, inner, f"{prefix}{vk}.")
            return

        # ② 具名属性校验
        if isinstance(value, dict):
            props = sch.get("properties") or {}
            if not props and sch.get("type") == "object":
                return  # 开放字典（如 auth_spec/profiles）：不校验键名
            for k, v in value.items():
                full = f"{prefix}{k}"
                prop = props.get(k)
                if prop is None:
                    bad.append(full)
                    continue
                walk(v, _unwrap_model(prop, defs) or prop, full + "." if
                     _is_container(prop, defs) else full)
            return
        # 标量：无键可查

    def _unwrap_model(prop: Dict[str, Any],
                      defs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        stack = [prop]
        seen = 0
        while stack and seen < 6:
            cur = stack.pop()
            if "$ref" in cur:
                name = cur["$ref"].split("/")[-1]
                target = defs.get(name)
                if target is None:
                    return None
                stack.append({**target})
            if "anyOf" in cur:
                stack.extend(cur["anyOf"])
            if cur.get("type") == "object":
                return cur
            seen += 1
        return None

    def _is_container(prop: Dict[str, Any], defs: Dict[str, Any]) -> bool:
        if prop.get("type") == "array":
            return True
        resolved = _unwrap_model(prop, defs)
        return resolved is not None

    walk(patch, schema, prefix)
    return bad


def _read_yaml(path: Path, label: str) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        log.warning("%s 层配置 %s 解析失败，已忽略: %s", label, path, e)
        return {}


def _atomic_write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

