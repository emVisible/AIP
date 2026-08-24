import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * StepEditDialog —— 影刀式步骤编辑弹窗。
 *
 * 单一职责：一个步骤的查看与编辑（第三部 2.1）。
 * 数据流：open 时从 step 快照初始化 draft → 编辑 → 保存时整体回写。
 * 表单主体复用 SchemaForm（schema 驱动 + 变量引用），本组件不感知字段语义。
 */
import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { Badge, Button, Dialog, Field, Input, riskTone } from "../ui";
import { SchemaForm } from "./SchemaForm";
export function StepEditDialog({ open, step, meta, availableVars, onClose, onSave, onDelete, }) {
    const [draft, setDraft] = useState(null);
    // step 或 open 变化 → 重置 draft（prop 驱动的状态生命周期，第三部 2.5）
    useEffect(() => {
        setDraft(step ? { ...step } : null);
    }, [step, open]);
    const schema = useMemo(() => (meta?.params ?? null), [meta]);
    if (!draft)
        return _jsx(Dialog, { open: false, onClose: onClose, children: null });
    const title = draft.action || (draft.type ? `[${draft.type}]` : "未命名步骤");
    function patch(partial) {
        setDraft((prev) => (prev ? { ...prev, ...partial } : prev));
    }
    function setParam(key, value) {
        let params = {};
        try {
            params = JSON.parse(draft.params_json || "{}");
        }
        catch { /* 坏 JSON 重开 */ }
        params[key] = value;
        patch({ params_json: JSON.stringify(params, null, 2) });
    }
    function save() {
        onSave(draft);
        onClose();
    }
    return (_jsxs(Dialog, { open: open, onClose: onClose, width: 620, children: [_jsxs("div", { className: "px-4 py-3 border-b border-slate-100", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-800 truncate", children: title }), meta && _jsx(Badge, { tone: riskTone(meta.risk), children: meta.risk }), meta?.idempotency && (_jsx(Badge, { tone: "neutral", children: meta.idempotency }))] }), meta?.description && (_jsx("p", { className: "mt-0.5 text-[11px] text-slate-400", children: meta.description }))] }), _jsxs("div", { className: "px-4 py-3 space-y-4 max-h-[60vh] overflow-y-auto", children: [_jsx("section", { className: "space-y-3", children: _jsx(SchemaForm, { schema: schema, values: safeParse(draft.params_json), availableVars: availableVars, onChange: setParam }) }), _jsxs("details", { className: "group", children: [_jsx("summary", { className: "text-[11px] text-slate-400 cursor-pointer\n                              select-none hover:text-slate-600", children: "\u9AD8\u7EA7\u9009\u9879" }), _jsxs("div", { className: "mt-2 grid grid-cols-2 gap-3", children: [_jsx(Field, { label: "\u6B65\u9AA4 ID", children: _jsx(Input, { value: draft.id, onChange: (e) => patch({ id: e.target.value }) }) }), _jsx(Field, { label: "\u8F93\u51FA\u53D8\u91CF", hint: "output_as", children: _jsx(Input, { value: draft.output_as, onChange: (e) => patch({ output_as: e.target.value }) }) }), _jsx(Field, { label: "\u6267\u884C\u6761\u4EF6", hint: "Python \u8868\u8FBE\u5F0F", children: _jsx(Input, { value: draft.condition, placeholder: "steps.x.ok == true", onChange: (e) => patch({ condition: e.target.value }) }) }), _jsx(Field, { label: "\u5931\u8D25\u8DF3\u8F6C", hint: "\u6B65\u9AA4 ID", children: _jsx(Input, { value: draft.on_failure_goto, onChange: (e) => patch({ on_failure_goto: e.target.value }) }) })] })] })] }), _jsxs("div", { className: "flex items-center px-4 py-2.5 border-t border-slate-100\n                      bg-slate-50/50", children: [onDelete && (_jsxs(Button, { variant: "danger", size: "sm", onClick: () => { onDelete(); onClose(); }, children: [_jsx(Trash2, { size: 12 }), " \u5220\u9664"] })), _jsxs("div", { className: "ml-auto flex gap-2", children: [_jsx(Button, { variant: "ghost", size: "sm", onClick: onClose, children: "\u53D6\u6D88" }), _jsx(Button, { variant: "primary", size: "sm", onClick: save, children: "\u4FDD\u5B58" })] })] })] }));
}
function safeParse(json) {
    try {
        return JSON.parse(json || "{}");
    }
    catch {
        return {};
    }
}
