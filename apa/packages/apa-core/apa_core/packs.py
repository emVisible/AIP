"""apa-core: Capability Pack 架构（v0.13）。

三层能力体系中的 L-Pack 层：
  packs/<name>/pack.yaml + actions/*.yaml + executor 模块声明

发现三通道（优先级从低到高）：
  1. builtin   —— apa/packs/*/        （仓库内置）
  2. entry     —— pip 包 entry_points["apa.packs"]
  3. user      —— ~/.apa/packs/*/     （用户自定义，可覆盖同名）

冲突治理（axiom 1.2 单一真相）：
  action 同名默认 RegistryError；仅 pack.yaml overrides 显式声明的
  动作允许接管，并在加载结果中记录 audit 标记。
domain 多方提供时按 priority 字段裁决（缺省按通道顺序）。

协议零感知：本层只产出 (registry 片段路径, executor 装配清单)，
AIP 消息结构与路由规则完全不变——这是「接入 AIP 协议的基础」。
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None


class PackError(ValueError):
    pass


@dataclass
class PackManifest:
    name: str
    version: str
    source: str                      # builtin | entry | user
    root: Path
    provides_domains: List[str] = field(default_factory=list)
    registries: List[Path] = field(default_factory=list)
    executors: List[Dict[str, Any]] = field(default_factory=list)
    py_deps: List[str] = field(default_factory=list)
    overrides: List[str] = field(default_factory=list)


@dataclass
class LoadedPack:
    manifest: PackManifest
    registry_paths: List[Path]
    executor_specs: List[Dict[str, Any]]   # {module,class,domains}
    audit: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manifest 解析
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("name", "version")


def _parse_manifest(pack_dir: Path, source: str) -> PackManifest:
    if _yaml is None:
        raise PackError("PyYAML required")
    mf_path = pack_dir / "pack.yaml"
    if not mf_path.is_file():
        raise PackError(f"{pack_dir}: pack.yaml missing")
    raw = _yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
    for k in _REQUIRED_FIELDS:
        if not raw.get(k):
            raise PackError(f"{mf_path}: missing field {k!r}")

    registries: List[Path] = []
    for rel in raw.get("registries") or []:
        p = (pack_dir / rel).resolve()
        if not p.is_file():
            raise PackError(f"{mf_path}: registry file missing {rel!r}")
        registries.append(p)

    return PackManifest(
        name=str(raw["name"]),
        version=str(raw["version"]),
        source=source,
        root=pack_dir,
        provides_domains=[str(d) for d in
                           (raw.get("provides_domains") or [])],
        registries=registries,
        executors=list(raw.get("executors") or []),
        py_deps=[str(d) for d in (raw.get("py_deps") or [])],
        overrides=[str(o) for o in (raw.get("overrides") or [])],
    )


# ---------------------------------------------------------------------------
# 发现三通道
# ---------------------------------------------------------------------------

def discover_packs(*,
                   builtin_dir: Optional[Path] = None,
                   user_dir: Optional[Path] = None,
                   include_entry_points: bool = True,
                   ) -> List[PackManifest]:
    """返回按优先级排序的 manifest 列表（低→高：builtin→entry→user）。"""
    found: Dict[str, PackManifest] = {}

    # ① builtin
    if builtin_dir and Path(builtin_dir).is_dir():
        for d in sorted(Path(builtin_dir).iterdir()):
            if d.is_dir() and (d / "pack.yaml").is_file():
                m = _parse_manifest(d, "builtin")
                found[m.name] = m

    # ② entry_points（pip 安装的能力包）
    if include_entry_points:
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="apa.packs")
            for ep in eps:
                try:
                    obj = ep.load()
                    root = Path(str(obj))
                    if (root / "pack.yaml").is_file():
                        m = _parse_manifest(root, "entry")
                        found.setdefault(m.name, m)   # 不覆盖更高优先级
                except Exception:
                    continue
        except Exception:
            pass

    # ③ user（最高优先级）
    if user_dir and Path(user_dir).is_dir():
        for d in sorted(Path(user_dir).iterdir()):
            if d.is_dir() and (d / "pack.yaml").is_file():
                m = _parse_manifest(d, "user")
                found[m.name] = m       # user 覆盖同名校验后接管

    return list(found.values())


# ---------------------------------------------------------------------------
# 加载与冲突治理
# ---------------------------------------------------------------------------

def load_packs(manifests: List[PackManifest], *,
               reserved_actions: Optional[List[str]] = None) -> List[LoadedPack]:
    """加载包集合 → registry 路径与 executor 装配清单。

    reserved_actions：core 引擎已占用的动作名（如 ui.confirm /
    human.task.create），pack 不得声明。
    冲突策略：
      · pack 内动作与保留名冲突 → PackError
      · 两 pack 同一动作且后者未声明 override → PackError
    """
    seen_actions: Dict[str, str] = {
        a: "_core" for a in (reserved_actions or [])}
    loaded: List[LoadedPack] = []

    for m in manifests:
        audit: List[str] = []
        reg_paths: List[Path] = list(m.registries)

        if _yaml is not None:
            owned: set = set()
            for rp in m.registries:
                doc = _yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
                for act_name in doc:
                    owned.add(str(act_name))
                    prev = seen_actions.get(act_name)
                    if prev is not None and prev != m.name:
                        if act_name in m.overrides:
                            audit.append(
                                f"override {act_name} (was {prev})")
                        else:
                            raise PackError(
                                f"pack {m.name!r}: action {act_name!r} "
                                f"already provided by {prev!r} — "
                                "declare in overrides to take over")
            seen_actions.update({a: m.name for a in owned})

        executor_specs = []
        for spec in m.executors:
            executor_specs.append({
                "module": str(spec.get("module", "")),
                "class": str(spec.get("class", "")),
                "domains": [str(d) for d in
                             (spec.get("domains") or [])],
            })

        loaded.append(LoadedPack(manifest=m, registry_paths=reg_paths,
                                  executor_specs=executor_specs,
                                  audit=audit))
    return loaded


def instantiate_executor(spec: Dict[str, str],
                          source: str, session_id: str, **kwargs):
    """按装配清单实例化 executor（延迟导入，失败抛 PackError 链）。"""
    try:
        mod = importlib.import_module(spec["module"])
        cls = getattr(mod, spec["class"])
        return cls(source, session_id, **kwargs)
    except Exception as e:
        raise PackError(
            f"executor {spec['module']}.{spec['class']} "
            f"instantiation failed: {e}") from e