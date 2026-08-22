import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Handle, Position } from "@xyflow/react";
/** 自定义步骤节点 —— 职责单一：仅渲染，交互由画布层处理。 */
export function StepNode({ data }) {
    const { step, selected } = data;
    const isAI = step.type === "ai_decision";
    const tone = selected
        ? "border-brand ring-2 ring-blue-200"
        : isAI
            ? "border-purple-300 bg-purple-50"
            : "border-slate-300 bg-white";
    return (_jsxs("div", { className: `rounded-lg border px-3 py-2 min-w-[140px] shadow-sm ${tone}`, children: [_jsx(Handle, { type: "target", position: Position.Top, className: "!w-1.5 !h-1.5" }), _jsxs("p", { className: `text-xs font-semibold ${isAI ? "text-purple-700" : "text-slate-700"}`, children: [isAI ? "⚡ " : "", step.id] }), step.action && (_jsx("p", { className: "text-[11px] text-slate-500 mt-0.5 truncate", children: step.action })), step.condition && (_jsxs("p", { className: "text-[10px] text-amber-600 mt-0.5 truncate", children: ["? ", step.condition] })), _jsx(Handle, { type: "source", position: Position.Bottom, className: "!w-1.5 !h-1.5" })] }));
}
