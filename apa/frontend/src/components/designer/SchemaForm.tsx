/**
 * Schema 驱动的动态参数表单生成器。
 *
 * 从 Action Registry 的 JSON Schema 自动渲染对应的表单控件。
 * 每个字段支持两种输入模式：直接值 | 变量引用（从前面步骤选择）。
 *
 * 设计模式：策略模式 —— 根据 schema type 分派到不同的控件组件。
 */
import { useEffect, useRef, useState } from "react";
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
  const btnRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // U3: fixed 定位 + 实时坐标 —— 逃逸弹窗 overflow 裁剪
  function toggle() {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const width = 256;
      setPos({
        top: Math.min(r.bottom + 4, window.innerHeight - 200),
        left: Math.max(8, Math.min(r.right - width,
                                   window.innerWidth - width - 8)),
      });
    }
    setOpen(!open);
  }

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  if (!vars.length) return null;
  return (
    <div className="relative">
      <button ref={btnRef}
        type="button"
        onClick={toggle}
        className="text-[10px] text-blue-500 hover:text-blue-700 px-1"
        title="引用前序步骤输出"
      >{"{}"}</button>
      {open && pos && (
        <div style={{ position: "fixed", top: pos.top, left: pos.left,
                      width: 256 }}
             className="z-[60] bg-white border rounded-lg shadow-lg
                        max-h-48 overflow-y-auto">
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
function FieldControl({ prop, value, onChange, alert }: {
  prop: SchemaProp; value: unknown; onChange: (v: unknown) => void;
  /** 必填缺空高亮（S2-T3）。 */
  alert?: boolean;
}) {
  const t = prop.type ?? "string";
  const border = alert
    ? "border-red-400 ring-1 ring-red-200"
    : "border-slate-200";

  if (prop.enum && Array.isArray(prop.enum)) {
    return (
      <select
        className={`w-full px-2 py-1.5 text-xs border rounded-md
                   focus:ring-1 focus:ring-blue-400 outline-none
                   transition-shadow duration-150 ${border}`}
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
          className={`w-full px-2 py-1.5 text-xs border rounded-md
                     focus:ring-1 focus:ring-blue-400 outline-none
                     transition-shadow duration-150 ${border}`}
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
                      transition-colors duration-150 ${value
            ? "bg-emerald-50 text-emerald-700 border-emerald-200"
            : "bg-slate-50 text-slate-500 border-slate-200"}
                      ${alert ? " ring-1 ring-red-300" : ""}`}
        >{value ? "是" : "否"}</button>
      );
    default: {
      // S2-T2：空值时 placeholder 优先展示 default，而非 description。
      const showDefault = (value == null || value === "") &&
        prop.default != null;
      return (
        <input
          type="text"
          className={`w-full px-2 py-1.5 text-xs border rounded-md
                     focus:ring-1 focus:ring-blue-400 outline-none
                     transition-shadow duration-150 ${border}`}
          placeholder={showDefault
            ? `默认：${String(prop.default)}`
            : prop.description}
          value={value != null ? String(value) : ""}
          onChange={e => onChange(e.target.value)}
        />
      );
    }
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
  // S2-T1：高级折叠显隐（CSS grid-rows 动画，见下方）。
  const [advOpen, setAdvOpen] = useState(false);

  if (!schema?.properties || !Object.keys(schema.properties).length) {
    return (
      <p className="text-xs text-slate-400 p-2">
        该动作无参数，或未加载动作定义</p>
    );
  }

  const required = new Set(schema.required ?? []);
  const entries = Object.entries(schema.properties);
  // S2-T1：必填常驻在上，可选收进高级。是否必填是唯一分层依据，
  // 与有无 default 无关——有 default 的必填项仍常驻（值可见、可恢复）。
  const main = entries.filter(([k]) => required.has(k));
  const adv = entries.filter(([k]) => !required.has(k));

  const isEmpty = (v: unknown) =>
    v == null || (typeof v === "string" && v.trim() === "");
  const sameAsDefault = (key: string, prop: SchemaProp) =>
    prop.default !== undefined &&
    JSON.stringify(values[key] ?? null) ===
      JSON.stringify(prop.default ?? null);

  function renderField(key: string, prop: SchemaProp, isRequired: boolean) {
    const varMatches = availableVars.filter(
      v => v.path.includes(key) || v.sourceAction === key.split("_")[0]);
    // S2-T3：必填缺空才高亮；"0"/false 是合法值，不算空。
    const invalid = isRequired && isEmpty(values[key]);

    return (
      <div key={key} className="space-y-0.5">
        <label className="flex items-center justify-between text-[11px]">
          <span className={`inline-flex items-center gap-1 ${isRequired
            ? "text-slate-700 font-medium" : "text-slate-500"}`}>
            {key}{isRequired && <span className="text-red-400 ml-0.5">*</span>}
            {invalid && (
              <span className="text-[9px] leading-none rounded bg-red-50
                               text-red-500 px-1 py-0.5 font-medium
                               animate-fade-in">
                待填
              </span>
            )}
          </span>
          <span className="inline-flex items-center">
            {/* S2-T2：值偏离 default 才出现恢复按钮 */}
            {prop.default !== undefined && !sameAsDefault(key, prop) && (
              <button type="button"
                title={`恢复默认：${String(prop.default)}`}
                onClick={() => onChange(key, prop.default)}
                className="text-[10px] text-slate-400 hover:text-blue-600
                           px-1 transition-colors duration-150">
                ↺默认
              </button>
            )}
            <VarPicker vars={varMatches.length ? varMatches : availableVars}
                       onPick={(path) => onChange(key, `{{${path}}}`)} />
          </span>
        </label>
        <FieldControl prop={prop} value={values[key]}
                      alert={invalid}
                      onChange={v => onChange(key, v)} />
        {prop.description && (
          <p className="text-[10px] text-slate-300">{prop.description}</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* S2-T5：零必填=开箱即用，明确告诉用户不用填 */}
      {main.length === 0 && (
        <p className="text-[11px] text-emerald-600 bg-emerald-50/60
                      border border-emerald-100 rounded-md px-2 py-1.5">
          ✓ 开箱即用，无需填写{adv.length > 0 ? "（微调见高级）" : ""}</p>
      )}
      {main.map(([k, p]) => renderField(k, p, true))}
      {adv.length > 0 && (
        <div>
          <button type="button" onClick={() => setAdvOpen(o => !o)}
            className="w-full flex items-center justify-between text-[11px]
                       text-slate-400 hover:text-slate-600 px-0.5 py-1
                       transition-colors duration-150">
            <span>高级（{adv.length}）</span>
            <span className={`inline-block transition-transform duration-200
                              ${advOpen ? "rotate-180" : ""}`}>▾</span>
          </button>
          <div className={`grid transition-all duration-200 ease-out
                           ${advOpen
                             ? "grid-rows-[1fr] opacity-100"
                             : "grid-rows-[0fr] opacity-0"}`}>
            <div className="overflow-hidden">
              <div className="space-y-3 pt-1">
                {adv.map(([k, p]) => renderField(k, p, false))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}