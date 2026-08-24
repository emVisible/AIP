/**
 * Schema 驱动的动态参数表单生成器。
 *
 * 从 Action Registry 的 JSON Schema 自动渲染对应的表单控件。
 * 每个字段支持两种输入模式：直接值 | 变量引用（从前面步骤选择）。
 *
 * 设计模式：策略模式 —— 根据 schema type 分派到不同的控件组件。
 */
import { useState } from "react";
import type { VariableInfo } from "../../hooks/useVariableRegistry";

interface SchemaProp {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  pattern?: string;
}

interface ParamSchema {
  type?: string;
  properties?: Record<string, SchemaProp>;
  required?: string[];
}

// ---- 单个字段的变量选择器 ----
function VarPicker({ vars, onPick }: {
  vars: VariableInfo[]; onPick: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!vars.length) return null;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-[10px] text-blue-500 hover:text-blue-700 px-1"
        title="引用前序步骤输出"
      >{"{}"}</button>
      {open && (
        <div className="absolute z-50 mt-1 w-64 bg-white border rounded-lg shadow-lg
                        max-h-48 overflow-y-auto right-0">
          {vars.map(v => (
            <div key={v.path}
              className="px-3 py-1.5 hover:bg-blue-50 cursor-pointer text-xs"
              onClick={() => { onPick(v.path); setOpen(false); }}>
              <span className="font-mono text-blue-600">{`{{${v.path}}}`}</span>
              <span className="text-slate-400 ml-2">{v.preview}</span>
              <span className="text-slate-300 ml-1 text-[10px]">←{v.stepId}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- 类型化控件 ----
function FieldControl({ prop, value, onChange }: {
  prop: SchemaProp; value: unknown; onChange: (v: unknown) => void;
}) {
  const t = prop.type ?? "string";

  if (prop.enum && Array.isArray(prop.enum)) {
    return (
      <select
        className="w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md
                   focus:ring-1 focus:ring-blue-400 outline-none"
        value={String(value ?? "")}
        onChange={e => onChange(e.target.value)}
      >
        <option value="">— 选择 —</option>
        {prop.enum.map(opt => (
          <option key={String(opt)} value={String(opt)}>{String(opt)}</option>
        ))}
      </select>
    );
  }

  switch (t) {
    case "number":
    case "integer":
      return (
        <input
          type="number"
          className="w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md
                     focus:ring-1 focus:ring-blue-400 outline-none"
          value={value != null ? String(value) : ""}
          onChange={e => onChange(e.target.value ? Number(e.target.value) : undefined)}
        />
      );
    case "boolean":
      return (
        <button
          type="button"
          onClick={() => onChange(!value)}
          className={`w-full py-1.5 text-xs font-medium rounded-md border
                      transition-colors ${value
            ? "bg-emerald-50 text-emerald-700 border-emerald-200"
            : "bg-slate-50 text-slate-500 border-slate-200"}`}
        >{value ? "是" : "否"}</button>
      );
    default:
      return (
        <input
          type="text"
          className="w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md
                     focus:ring-1 focus:ring-blue-400 outline-none"
          placeholder={prop.description}
          value={value != null ? String(value) : ""}
          onChange={e => onChange(e.target.value)}
        />
      );
  }
}

// ---- 主组件 ----
export function SchemaForm({
  schema,
  values,
  availableVars,
  onChange,
}: {
  schema: ParamSchema | null;
  values: Record<string, unknown>;
  availableVars: VariableInfo[];
  onChange: (key: string, value: unknown) => void;
}) {
  if (!schema?.properties || !Object.keys(schema.properties).length) {
    return (
      <p className="text-xs text-slate-400 p-2">
        该动作无参数，或未加载动作定义</p>
    );
  }

  const required = new Set(schema.required ?? []);

  return (
    <div className="space-y-3">
      {Object.entries(schema.properties).map(([key, prop]) => {
        const isRequired = required.has(key);
        const varMatches = availableVars.filter(
          v => v.path.includes(key) || v.sourceAction === key.split("_")[0]);

        return (
          <div key={key} className="space-y-0.5">
            <label className="flex items-center justify-between text-[11px]">
              <span className={isRequired ? "text-slate-700 font-medium"
                                       : "text-slate-500"}>
                {key}{isRequired && <span className="text-red-400 ml-0.5">*</span>}
              </span>
              <VarPicker vars={varMatches.length ? varMatches : availableVars}
                         onPick={(path) => onChange(key, `{{${path}}}`)} />
            </label>
            <FieldControl prop={prop} value={values[key]}
                          onChange={v => onChange(key, v)} />
            {prop.description && (
              <p className="text-[10px] text-slate-300">{prop.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}