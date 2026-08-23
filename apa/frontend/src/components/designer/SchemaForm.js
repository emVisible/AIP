import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Schema 驱动的动态参数表单生成器。
 *
 * 从 Action Registry 的 JSON Schema 自动渲染对应的表单控件。
 * 每个字段支持两种输入模式：直接值 | 变量引用（从前面步骤选择）。
 *
 * 设计模式：策略模式 —— 根据 schema type 分派到不同的控件组件。
 */
import { useState } from "react";
// ---- 单个字段的变量选择器 ----
function VarPicker({ vars, onPick }) {
    const [open, setOpen] = useState(false);
    if (!vars.length)
        return null;
    return (_jsxs("div", { className: "relative", children: [_jsx("button", { type: "button", onClick: () => setOpen(!open), className: "text-[10px] text-blue-500 hover:text-blue-700 px-1", title: "\u5F15\u7528\u524D\u5E8F\u6B65\u9AA4\u8F93\u51FA", children: "{}" }), open && (_jsx("div", { className: "absolute z-50 mt-1 w-64 bg-white border rounded-lg shadow-lg\n                        max-h-48 overflow-y-auto right-0", children: vars.map(v => (_jsxs("div", { className: "px-3 py-1.5 hover:bg-blue-50 cursor-pointer text-xs", onClick: () => { onPick(v.path); setOpen(false); }, children: [_jsx("span", { className: "font-mono text-blue-600", children: `{{${v.path}}}` }), _jsx("span", { className: "text-slate-400 ml-2", children: v.preview }), _jsxs("span", { className: "text-slate-300 ml-1 text-[10px]", children: ["\u2190", v.stepId] })] }, v.path))) }))] }));
}
// ---- 类型化控件 ----
function FieldControl({ prop, value, onChange }) {
    const t = prop.type ?? "string";
    if (prop.enum && Array.isArray(prop.enum)) {
        return (_jsxs("select", { className: "w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md\n                   focus:ring-1 focus:ring-blue-400 outline-none", value: String(value ?? ""), onChange: e => onChange(e.target.value), children: [_jsx("option", { value: "", children: "\u2014 \u9009\u62E9 \u2014" }), prop.enum.map(opt => (_jsx("option", { value: String(opt), children: String(opt) }, String(opt))))] }));
    }
    switch (t) {
        case "number":
        case "integer":
            return (_jsx("input", { type: "number", className: "w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md\n                     focus:ring-1 focus:ring-blue-400 outline-none", value: value != null ? String(value) : "", onChange: e => onChange(e.target.value ? Number(e.target.value) : undefined) }));
        case "boolean":
            return (_jsx("button", { type: "button", onClick: () => onChange(!value), className: `w-full py-1.5 text-xs font-medium rounded-md border
                      transition-colors ${value
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-slate-50 text-slate-500 border-slate-200"}`, children: value ? "✓ 是" : "✗ 否" }));
        default:
            return (_jsx("input", { type: "text", className: "w-full px-2 py-1.5 text-xs border border-slate-200 rounded-md\n                     focus:ring-1 focus:ring-blue-400 outline-none", placeholder: prop.description, value: value != null ? String(value) : "", onChange: e => onChange(e.target.value) }));
    }
}
// ---- 主组件 ----
export function SchemaForm({ schema, values, availableVars, onChange, }) {
    if (!schema?.properties || !Object.keys(schema.properties).length) {
        return (_jsx("p", { className: "text-xs text-slate-400 p-2", children: "\u8BE5\u52A8\u4F5C\u65E0\u53C2\u6570\uFF0C\u6216\u672A\u52A0\u8F7D\u52A8\u4F5C\u5B9A\u4E49" }));
    }
    const required = new Set(schema.required ?? []);
    return (_jsx("div", { className: "space-y-3", children: Object.entries(schema.properties).map(([key, prop]) => {
            const isRequired = required.has(key);
            const varMatches = availableVars.filter(v => v.path.includes(key) || v.sourceAction === key.split("_")[0]);
            return (_jsxs("div", { className: "space-y-0.5", children: [_jsxs("label", { className: "flex items-center justify-between text-[11px]", children: [_jsxs("span", { className: isRequired ? "text-slate-700 font-medium"
                                    : "text-slate-500", children: [key, isRequired && _jsx("span", { className: "text-red-400 ml-0.5", children: "*" })] }), _jsx(VarPicker, { vars: varMatches.length ? varMatches : availableVars, onPick: (path) => onChange(key, `{{${path}}}`) })] }), _jsx(FieldControl, { prop: prop, value: values[key], onChange: v => onChange(key, v) }), prop.description && (_jsx("p", { className: "text-[10px] text-slate-300", children: prop.description }))] }, key));
        }) }));
}
