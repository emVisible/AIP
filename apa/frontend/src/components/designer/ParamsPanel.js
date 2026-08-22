import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useDesignerStore } from "../../pages/designer/designerStore";
/** 属性面板：选中步骤的参数编辑（职责单一：只编辑当前选中项）。 */
export function ParamsPanel() {
    const { steps, selectedIdx, updateStep } = useDesignerStore();
    const step = selectedIdx != null ? steps[selectedIdx] : undefined;
    if (!step) {
        return _jsx("p", { className: "text-xs text-slate-400 p-3", children: "\u70B9\u51FB\u753B\u5E03\u4E2D\u7684\u6B65\u9AA4\u8282\u70B9\u4EE5\u7F16\u8F91\u5C5E\u6027" });
    }
    const field = (key, label, placeholder) => (_jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: label }), _jsx("input", { className: "w-full px-2 py-1 text-xs border border-slate-200 rounded", value: step[key] ?? "", placeholder: placeholder, onChange: (e) => updateStep(selectedIdx, { [key]: e.target.value }) })] }));
    return (_jsxs("div", { className: "space-y-2 p-1", children: [_jsxs("p", { className: "text-[10px] font-semibold text-slate-400 uppercase", children: ["\u6B65\u9AA4\u5C5E\u6027 \u2014 ", step.id] }), field("id", "步骤 ID"), field("action", "动作名"), field("target", "target（可选）"), _jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "\u53C2\u6570 (JSON)" }), _jsx("textarea", { className: "w-full px-2 py-1 text-xs font-mono border border-slate-200\n                     rounded resize-y", rows: 4, value: step.params_json, onChange: (e) => updateStep(selectedIdx, { params_json: e.target.value }) })] }), field("condition", "condition（原始表达式，留空跳过）"), field("output_as", "output_as（结果别名）"), field("on_failure_goto", "失败 goto key（可选）")] }));
}
