import { useState } from "react";

import type { DStep } from "../../types/designer";
import {
  TRIGGER_VARS,
  type VariableInfo,
} from "../../hooks/useVariableRegistry";

/** 属性面板：选中步骤的参数编辑（schema 驱动 + 变量引用）。 */
export function ParamsPanel({ steps, selectedIdx, onUpdate, catalog }: {
  steps: DStep[];
  selectedIdx: number | null;
  onUpdate: (i: number, patch: Partial<DStep>) => void;
  catalog: Record<string, import("../../api/types").ActionMeta>;
}) {
  const step = selectedIdx != null ? steps[selectedIdx] : undefined;

  if (!step) {
    return (
      <p className="text-xs text-slate-400 p-3">
        点击画布中的步骤以编辑属性</p>
    );
  }

  const meta = catalog[step.action];
  const schema = (meta?.params ?? null) as ParamSchema | null;

  let params: Record<string, unknown> = {};
  try { params = JSON.parse(step.params_json || "{}"); } catch {}

  // 当前步骤之前可用的变量
  const vars = [
    ...TRIGGER_VARS,
    ...steps.slice(0, selectedIdx ?? 0).flatMap(s => {
      const out: VariableInfo[] = [];
      try {
        const params = JSON.parse(s.params_json || "{}");
        for (const [k, v] of Object.entries(params)) {
          out.push({
            path: `${s.id}.${k}`, stepId: s.id,
            sourceAction: s.action, preview: String(v),
          });
        }
      } catch {}
      return out;
    }),
  ];

  return (
    <div className="space-y-3 p-1">
      {/* 动作信息 */}
      <div className="rounded-md bg-blue-50 px-3 py-2">
        <p className="text-xs font-semibold text-blue-700">{step.id}</p>
        <p className="text-[10px] text-slate-500">{meta?.description ?? step.action}</p>
        <span className={`inline-block mt-1 text-[10px] rounded px-1.5 py-0.5 ${
          meta?.risk.startsWith("L0") ? "bg-emerald-50 text-emerald-600"
          : meta?.risk.startsWith("L1") ? "bg-blue-50 text-blue-600"
          : meta?.risk.startsWith("L2") ? "bg-amber-50 text-amber-600"
          : "bg-red-50 text-red-600"
        }`}>{meta?.risk ?? "?"}</span>
      </div>

      {/* Schema 驱动参数表单 */}
      <SchemaFormWrapper
        schema={schema}
        values={params}
        vars={vars}
        onChange={(key, value) => {
          const newParams = { ...params, [key]: value };
          onUpdate(selectedIdx!, {
            params_json: JSON.stringify(newParams, null, 2),
          });
        }}
      />

      {/* 高级字段 */}
      <details>
        <summary className="text-[11px] text-slate-400 cursor-pointer">高级</summary>
        <div className="space-y-2 pt-1">
          <div>
            <label className="text-[11px] text-slate-400">output_as</label>
            <input className="w-full px-2 py-1 text-xs border rounded"
              value={step.output_as}
              onChange={e => onUpdate(selectedIdx!, { output_as: e.target.value })}/>
          </div>
          <div>
            <label className="text-[11px] text-slate-400">on_failure goto</label>
            <input className="w-full px-2 py-1 text-xs border rounded"
              value={step.on_failure_goto}
              onChange={e => onUpdate(selectedIdx!, { on_failure_goto: e.target.value })}/>
          </div>
        </div>
      </details>
    </div>
  );
}

interface ParamSchema {
  type?: string;
  properties?: Record<string, SchemaProp>;
  required?: string[];
}

interface SchemaProp {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
}

function SchemaFormWrapper({ schema, values, vars, onChange }: {
  schema: ParamSchema | null;
  values: Record<string, unknown>;
  vars: VariableInfo[];
  onChange: (key: string, value: unknown) => void;
}) {
  if (!schema || !Object.keys(schema).length) {
    return <p className="text-xs text-slate-400 p-2">（无参数定义）</p>;
  }

  const required = new Set(schema.required ?? []);
  const props = Object.entries(schema.properties ?? {});

  if (!props.length) {
    return <p className="text-xs text-slate-400 p-2">（无参数）</p>;
  }

  return (
    <div className="space-y-3">
      {props.map(([key, prop]) => {
        const isRequired = required.has(key);
        const matchingVars = vars.filter(v =>
          v.path.includes(key) || v.sourceAction === key);

        return (
          <div key={key} className="space-y-0.5">
            <label className="flex items-center justify-between text-[11px]">
              <span className={isRequired ? "text-slate-700 font-medium"
                                       : "text-slate-500"}>
                {key}{isRequired && <span className="text-red-400 ml-0.5">*</span>}
              </span>
              <VariablePicker vars={matchingVars.length ? matchingVars : vars}
                              onPick={path => onChange(key, `{{${path}}}`)} />
            </label>
            <SchemaField prop={prop} value={values[key]}
                         onChange={v => onChange(key, v)} />
          </div>
        );
      })}
    </div>
  );
}

function VariablePicker({ vars, onPick }: {
  vars: VariableInfo[]; onPick: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!vars.length) return null;
  return (
    <div className="relative inline-block">
      <button
        type="button" onClick={() => setOpen(!open)}
        className="text-[10px] text-blue-500 hover:text-blue-700 font-mono"
        title="引用前序步骤输出"
      >{"{v}"}</button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-1 w-72 bg-white border rounded-lg shadow-xl
                          max-h-56 overflow-y-auto right-0">
            {vars.map(v => (
              <div key={v.path}
                onClick={() => { onPick(`{{${v.path}}}`); setOpen(false); }}
                className="px-3 py-1.5 hover:bg-blue-50 cursor-pointer text-xs">
                <code className="text-blue-600">{`{{${v.path}}}`}</code>
                <span className="text-slate-300 ml-2">{v.preview}</span>
                <span className="text-slate-300 ml-1 text-[10px]">←{v.stepId}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SchemaField({ prop, value, onChange }: {
  prop: SchemaProp; value: unknown; onChange: (v: unknown) => void;
}) {
  const t = prop.type ?? "string";

  if (prop.enum && Array.isArray(prop.enum)) {
    return (
      <select
        className="w-full px-2 py-1.5 text-xs border rounded-md focus:ring-1
                   focus:ring-blue-400 outline-none"
        value={String(value ?? "")}
        onChange={e => onChange(e.target.value)}
      >
        <option value="">— 选择 —</option>
        {prop.enum.map(o => (
          <option key={String(o)} value={String(o)}>{String(o)}</option>
        ))}
      </select>
    );
  }

  switch (t) {
    case "number": case "integer":
      return (
        <input type="number"
          className="w-full px-2 py-1.5 text-xs border rounded-md outline-none"
          value={value != null ? String(value) : ""}
          onChange={e => onChange(Number(e.target.value))}
        />);
    case "boolean":
      return (
        <button type="button"
          onClick={() => onChange(!value)}
          className={`w-full py-1 text-xs rounded border transition-colors ${
            value ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-slate-50 text-slate-400 border-slate-200"}`}
        >{value ? "是" : "否"}</button>);
    default:
      return (
        <input type="text"
          className="w-full px-2 py-1.5 text-xs border rounded-md outline-none"
          placeholder={prop.description}
          value={value != null ? String(value) : ""}
          onChange={e => onChange(e.target.value)}
        />);
  }
}