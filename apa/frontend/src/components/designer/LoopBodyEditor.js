import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * 循环体编辑器（P20-C）—— foreach 步骤的子步骤可视化列表。
 *
 * 单一职责：body_steps 数组的增/删/上下移/参数编辑。
 * 子步骤参数用紧凑 JSON 文本域（与主画布卡片同级复杂度），
 * 不嵌套弹窗 —— 避免弹窗中弹窗。
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button, IconButton, Input, Textarea } from "../ui";
export function LoopBodyEditor({ steps: bodySteps, onChange }) {
    function update(i, patch) {
        onChange(bodySteps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
    }
    function remove(i) {
        onChange(bodySteps.filter((_, j) => j !== i));
    }
    function move(i, dir) {
        const to = i + dir;
        if (to < 0 || to >= bodySteps.length)
            return;
        const next = [...bodySteps];
        const [m] = next.splice(i, 1);
        next.splice(to, 0, m);
        onChange(next);
    }
    function add() {
        onChange([...bodySteps, {
                id: `b${bodySteps.length + 1}`,
                type: "", action: "", target: "",
                params_json: "{}", condition: "", output_as: "",
                on_failure_goto: "",
            }]);
    }
    return (_jsxs("div", { className: "space-y-1.5", children: [!bodySteps.length && (_jsx("p", { className: "text-[10px] text-slate-400", children: "\u5FAA\u73AF\u4F53\u4E3A\u7A7A\u2014\u2014\u6DFB\u52A0\u81F3\u5C11\u4E00\u4E2A\u6B65\u9AA4\uFF08\u6BCF\u8F6E\u8FED\u4EE3\u6309\u987A\u5E8F\u6267\u884C\uFF09" })), bodySteps.map((s, i) => (_jsxs("div", { className: "rounded-md border border-slate-200 bg-white\n                                px-2 py-1.5 space-y-1", children: [_jsxs("div", { className: "flex items-center gap-1", children: [_jsx("span", { className: "text-[10px] font-semibold text-slate-400\n                             w-4", children: i + 1 }), _jsx(Input, { className: "h-6 flex-1 text-[11px] font-mono", placeholder: "action \u540D", value: s.action, onChange: (e) => update(i, { action: e.target.value }) }), _jsx(Input, { className: "h-6 w-20 text-[11px] font-mono", placeholder: "id", value: s.id, onChange: (e) => update(i, { id: e.target.value }) }), _jsx(IconButton, { label: "\u4E0A\u79FB", onClick: () => move(i, -1), disabled: i === 0, children: _jsx(ArrowUp, { size: 11 }) }), _jsx(IconButton, { label: "\u4E0B\u79FB", onClick: () => move(i, 1), disabled: i === bodySteps.length - 1, children: _jsx(ArrowDown, { size: 11 }) }), _jsx(IconButton, { label: "\u5220\u9664", onClick: () => remove(i), className: "hover:text-red-600", children: _jsx(Trash2, { size: 11 }) })] }), _jsx(Textarea, { rows: 2, className: "font-mono text-[10px]", placeholder: '{"target": "{{row.id}}"}', value: s.params_json, onChange: (e) => update(i, { params_json: e.target.value }) }), s.condition && (_jsxs("p", { className: "text-[10px] text-amber-500 truncate", children: ["\u6761\u4EF6 ", s.condition] }))] }, i))), _jsxs(Button, { size: "sm", variant: "ghost", onClick: add, className: "w-full border border-dashed border-slate-300", children: [_jsx(Plus, { size: 12 }), " \u6DFB\u52A0\u5FAA\u73AF\u4F53\u6B65\u9AA4"] })] }));
}
