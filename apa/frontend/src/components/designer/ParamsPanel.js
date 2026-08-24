import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from "react";
import { TRIGGER_VARS, } from "../../hooks/useVariableRegistry";
/** 属性面板：选中步骤的参数编辑（schema 驱动 + 变量引用）。 */
export function ParamsPanel({ steps, selectedIdx, onUpdate, catalog }) {
    const step = selectedIdx != null ? steps[selectedIdx] : undefined;
    if (!step) {
        return (_jsx("p", { className: "text-xs text-slate-400 p-3", children: "\u70B9\u51FB\u753B\u5E03\u4E2D\u7684\u6B65\u9AA4\u4EE5\u7F16\u8F91\u5C5E\u6027" }));
    }
    const meta = catalog[step.action];
    const schema = (meta?.params ?? null);
    let params = {};
    try {
        params = JSON.parse(step.params_json || "{}");
    }
    catch { }
    // 当前步骤之前可用的变量
    const vars = [
        ...TRIGGER_VARS,
        ...steps.slice(0, selectedIdx ?? 0).flatMap(s => {
            const out = [];
            try {
                const params = JSON.parse(s.params_json || "{}");
                for (const [k, v] of Object.entries(params)) {
                    out.push({
                        path: `${s.id}.${k}`, stepId: s.id,
                        sourceAction: s.action, preview: String(v),
                    });
                }
            }
            catch { }
            return out;
        }),
    ];
    return (_jsxs("div", { className: "space-y-3 p-1", children: [_jsxs("div", { className: "rounded-md bg-blue-50 px-3 py-2", children: [_jsx("p", { className: "text-xs font-semibold text-blue-700", children: step.id }), _jsx("p", { className: "text-[10px] text-slate-500", children: meta?.description ?? step.action }), _jsx("span", { className: `inline-block mt-1 text-[10px] rounded px-1.5 py-0.5 ${meta?.risk.startsWith("L0") ? "bg-emerald-50 text-emerald-600"
                            : meta?.risk.startsWith("L1") ? "bg-blue-50 text-blue-600"
                                : meta?.risk.startsWith("L2") ? "bg-amber-50 text-amber-600"
                                    : "bg-red-50 text-red-600"}`, children: meta?.risk ?? "?" })] }), _jsx(SchemaFormWrapper, { schema: schema, values: params, vars: vars, onChange: (key, value) => {
                    const newParams = { ...params, [key]: value };
                    onUpdate(selectedIdx, {
                        params_json: JSON.stringify(newParams, null, 2),
                    });
                } }), _jsxs("details", { children: [_jsx("summary", { className: "text-[11px] text-slate-400 cursor-pointer", children: "\u9AD8\u7EA7" }), _jsxs("div", { className: "space-y-2 pt-1", children: [_jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "output_as" }), _jsx("input", { className: "w-full px-2 py-1 text-xs border rounded", value: step.output_as, onChange: e => onUpdate(selectedIdx, { output_as: e.target.value }) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "on_failure goto" }), _jsx("input", { className: "w-full px-2 py-1 text-xs border rounded", value: step.on_failure_goto, onChange: e => onUpdate(selectedIdx, { on_failure_goto: e.target.value }) })] })] })] })] }));
}
function SchemaFormWrapper({ schema, values, vars, onChange }) {
    if (!schema || !Object.keys(schema).length) {
        return _jsx("p", { className: "text-xs text-slate-400 p-2", children: "\uFF08\u65E0\u53C2\u6570\u5B9A\u4E49\uFF09" });
    }
    const required = new Set(schema.required ?? []);
    const props = Object.entries(schema.properties ?? {});
    if (!props.length) {
        return _jsx("p", { className: "text-xs text-slate-400 p-2", children: "\uFF08\u65E0\u53C2\u6570\uFF09" });
    }
    return (_jsx("div", { className: "space-y-3", children: props.map(([key, prop]) => {
            const isRequired = required.has(key);
            const matchingVars = vars.filter(v => v.path.includes(key) || v.sourceAction === key);
            return (_jsxs("div", { className: "space-y-0.5", children: [_jsxs("label", { className: "flex items-center justify-between text-[11px]", children: [_jsxs("span", { className: isRequired ? "text-slate-700 font-medium"
                                    : "text-slate-500", children: [key, isRequired && _jsx("span", { className: "text-red-400 ml-0.5", children: "*" })] }), _jsx(VariablePicker, { vars: matchingVars.length ? matchingVars : vars, onPick: path => onChange(key, `{{${path}}}`) })] }), _jsx(SchemaField, { prop: prop, value: values[key], onChange: v => onChange(key, v) })] }, key));
        }) }));
}
function VariablePicker({ vars, onPick }) {
    const [open, setOpen] = useState(false);
    if (!vars.length)
        return null;
    return (_jsxs("div", { className: "relative inline-block", children: [_jsx("button", { type: "button", onClick: () => setOpen(!open), className: "text-[10px] text-blue-500 hover:text-blue-700 font-mono", title: "\u5F15\u7528\u524D\u5E8F\u6B65\u9AA4\u8F93\u51FA", children: "{v}" }), open && (_jsxs(_Fragment, { children: [_jsx("div", { className: "fixed inset-0 z-40", onClick: () => setOpen(false) }), _jsx("div", { className: "absolute z-50 mt-1 w-72 bg-white border rounded-lg shadow-xl\n                          max-h-56 overflow-y-auto right-0", children: vars.map(v => (_jsxs("div", { onClick: () => { onPick(`{{${v.path}}}`); setOpen(false); }, className: "px-3 py-1.5 hover:bg-blue-50 cursor-pointer text-xs", children: [_jsx("code", { className: "text-blue-600", children: `{{${v.path}}}` }), _jsx("span", { className: "text-slate-300 ml-2", children: v.preview }), _jsxs("span", { className: "text-slate-300 ml-1 text-[10px]", children: ["\u2190", v.stepId] })] }, v.path))) })] }))] }));
}
function SchemaField({ prop, value, onChange }) {
    const t = prop.type ?? "string";
    if (prop.enum && Array.isArray(prop.enum)) {
        return (_jsxs("select", { className: "w-full px-2 py-1.5 text-xs border rounded-md focus:ring-1\n                   focus:ring-blue-400 outline-none", value: String(value ?? ""), onChange: e => onChange(e.target.value), children: [_jsx("option", { value: "", children: "\u2014 \u9009\u62E9 \u2014" }), prop.enum.map(o => (_jsx("option", { value: String(o), children: String(o) }, String(o))))] }));
    }
    switch (t) {
        case "number":
        case "integer":
            return (_jsx("input", { type: "number", className: "w-full px-2 py-1.5 text-xs border rounded-md outline-none", value: value != null ? String(value) : "", onChange: e => onChange(Number(e.target.value)) }));
        case "boolean":
            return (_jsx("button", { type: "button", onClick: () => onChange(!value), className: `w-full py-1 text-xs rounded border transition-colors ${value ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-slate-50 text-slate-400 border-slate-200"}`, children: value ? "是" : "否" }));
        default:
            return (_jsx("input", { type: "text", className: "w-full px-2 py-1.5 text-xs border rounded-md outline-none", placeholder: prop.description, value: value != null ? String(value) : "", onChange: e => onChange(e.target.value) }));
    }
}
