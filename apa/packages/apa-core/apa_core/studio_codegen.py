"""APA Studio Protocol TS 类型生成器（H3）。

用法：
  python -m apa_core.studio_codegen <输出路径.ts>

从 studio_protocol.py 的 pydantic 模型经 model_json_schema 单源生成
TS interface 文件。产物带 GENERATED 头，禁止手改；
pytest 门禁（test_studio_protocol.py::test_codegen_drift）比对漂移。

映射规则：
  string→string（enum→字面量联合） · integer/number→number · boolean
  array<T>→T[] · additionalProperties 对象→Record<string,U>
  $ref→嵌套模型名（TS interface 无声明顺序约束，递归按需输出）
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Set, Tuple

from pydantic import BaseModel

HEADER = """\
/**
 * APA Studio Protocol v1 —— GENERATED FILE, DO NOT EDIT.
 *
 * 单源: apa/packages/apa-core/apa_core/studio_protocol.py (pydantic)
 * 再生成: cd apa && python -m apa_core.studio_codegen frontend/src/shared/studioProtocol.ts
 */
"""


def _ts_type(schema: Dict[str, Any], deps: Set[str]) -> str:
    """JSON Schema 片段 → TS 类型表达式；$ref 记入依赖集合。"""
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        deps.add(name)
        return name
    if "anyOf" in schema:
        return " | ".join(_ts_type(s, deps) for s in schema["anyOf"])
    t = schema.get("type")
    if t == "string":
        enum = schema.get("enum")
        if enum:
            return " | ".join(f'"{v}"' for v in enum)
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"{_ts_type(schema.get('items') or {}, deps)}[]"
    if t == "object":
        addl = schema.get("additionalProperties")
        if isinstance(addl, dict):
            return f"Record<string, {_ts_type(addl, deps)}>"
        return "Record<string, unknown>"
    return "unknown"


def _collect_models() -> Dict[str, type]:
    from . import studio_protocol as sp

    found: Dict[str, type] = {}
    for name in dir(sp):
        obj = getattr(sp, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) \
                and obj is not BaseModel:
            found[name] = obj
    return found


def _sp_version() -> int:
    from . import studio_protocol as sp
    return sp.PROTOCOL_VERSION


def generate_ts() -> str:
    models = _collect_models()
    emitted: Set[str] = set()
    out: List[str] = [HEADER, "",
                      f"export const PROTOCOL_VERSION = "
                      f"{_sp_version()};", ""]
    body_of: Dict[str, List[Tuple[str, str, bool]]] = {}

    def collect(name: str) -> None:
        """递归收集：模型自身 + $ref 依赖的接口体。"""
        if name in emitted or name not in models:
            return
        emitted.add(name)
        schema = models[name].model_json_schema(
            ref_template="#/defs/{model}")
        deps: Set[str] = set()
        entries: List[Tuple[str, str, bool]] = []
        for pname, pschema in (schema.get("properties") or {}).items():
            required = pname in (schema.get("required") or [])
            entries.append((pname, _ts_type(pschema, deps), required))
        body_of[name] = entries
        for dep in sorted(deps):
            collect(dep)

    for name in sorted(models):
        collect(name)

    for name in sorted(body_of):
        out.append(f"export interface {name} {{")
        entries = body_of[name]
        if not entries:
            out.append("  [k: string]: unknown;")
        for pname, ts, required in entries:
            opt = "" if required else "?"
            out.append(f"  {pname}{opt}: {ts};")
        out.append("}")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else \
        "frontend/src/shared/studioProtocol.ts"
    text = generate_ts()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[studio-codegen] wrote {out_path} "
          f"({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
