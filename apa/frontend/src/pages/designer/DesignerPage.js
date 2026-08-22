import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * APA 低代码流程设计器（§10.2 模式 B 可视化编辑）。
 *
 * 三面板布局：动作目录（左）· React Flow 画布（中）· 属性+试运行（右）。
 * 步骤数组为逻辑执行顺序；画布位置仅视觉布局，不影响执行序。
 */
import { useCallback, useEffect, useState } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, useEdgesState, useNodesState, } from "@xyflow/react";
import { api } from "../../api/client";
function blankStep(i) {
    return {
        id: `step_${i + 1}`, type: "", action: "", target: "",
        params_json: "{}", condition: "", output_as: "",
        on_failure_goto: "",
    };
}
function StepNodeView({ data }) {
    return (_jsxs("div", { className: `rounded-lg border-2 px-3 py-2 min-w-[140px]
                     shadow-sm bg-white ${data.tone}`, children: [_jsx("p", { className: "text-xs font-semibold text-slate-700 truncate", children: data.label }), data.sub && (_jsx("p", { className: "text-[10px] text-slate-400 mt-0.5 truncate", children: data.sub }))] }));
}
const nodeTypes = { step: StepNodeView };
export function DesignerPage() {
    // ---- 状态 ----
    const [meta, setMeta] = useState({
        id: "", trigger_name: "", max_actions: 50
    });
    const [steps, setSteps] = useState([blankStep(0)]);
    const [yamlText, setYamlText] = useState("");
    const [statusMsg, setStatusMsg] = useState("就绪");
    const [processList, setProcessList] = useState([]);
    const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
    const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
    // ---- steps → RF 同步 ----
    const syncGraph = useCallback(() => {
        const nodes = steps.map((s, i) => ({
            id: s.id || `n${i}`,
            type: "step",
            position: { x: 200, y: i * 100 },
            data: {
                label: s.id || `step_${i + 1}`,
                sub: s.action || s.type || "",
                tone: s.condition ? "border-amber-300" : "border-slate-300",
            },
        }));
        const edges = [];
        for (let i = 0; i < steps.length - 1; i++) {
            edges.push({
                id: `e${i}`,
                source: steps[i].id || `n${i}`,
                target: steps[i + 1].id || `n${i + 1}`,
                animated: Boolean(steps[i].condition),
            });
        }
        setRfNodes(nodes);
        setRfEdges(edges);
    }, [steps, setRfNodes, setRfEdges]);
    useEffect(() => { syncGraph(); }, [syncGraph]);
    // ---- 步骤 CRUD ----
    const updateStep = useCallback((i, patch) => setSteps(prev => prev.map((s, j) => (j === i ? { ...s, ...patch } : s))), []);
    const addStep = useCallback(() => setSteps(prev => [...prev, blankStep(prev.length)]), []);
    const removeStep = useCallback((i) => setSteps(prev => prev.filter((_, j) => j !== i)), []);
    const moveStep = useCallback((i, dir) => setSteps(prev => {
        const next = [...prev];
        const j = i + dir;
        if (j < 0 || j >= next.length)
            return prev;
        const tmp = next[i];
        next[i] = next[j];
        next[j] = tmp;
        return next;
    }), []);
    // ---- YAML 双向 ----
    function buildForm() {
        return {
            id: meta.id,
            trigger_name: meta.trigger_name,
            max_actions: meta.max_actions,
            steps: steps.map(s => {
                let parsed = {};
                try {
                    parsed = JSON.parse(s.params_json || "{}");
                }
                catch { }
                return { ...s, params_json: undefined, params: parsed };
            }),
            error_handlers: [],
        };
    }
    async function syncToYaml() {
        try {
            const d = await api("/api/processes/from-form", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ form: buildForm() }),
            });
            setYamlText(d.yaml);
            setStatusMsg("已同步 YAML ✓");
        }
        catch (e) {
            setStatusMsg(`同步失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    async function loadFromYaml() {
        try {
            const d = await api("/api/processes/to-form", { method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ yaml: yamlText }) });
            setMeta({
                id: d.form.id, trigger_name: d.form.trigger_name,
                max_actions: d.form.max_actions,
            });
            setSteps(d.form.steps.map(s => ({
                ...s, params_json: typeof s.params_json === "string"
                    ? s.params_json : "{}",
            })));
            setStatusMsg("已从 YAML 加载表单 ✓");
        }
        catch (e) {
            setStatusMsg(`解析失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    async function save() {
        try {
            const form = buildForm();
            const yd = await api("/api/processes/from-form", { method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ form }) });
            await api("/api/processes/save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: meta.id || "untitled", yaml: yd.yaml
                }),
            });
            setStatusMsg(`已保存 ${meta.id} ✓`);
            void refreshProcessList();
        }
        catch (e) {
            setStatusMsg(`保存失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    async function openFile(fileId) {
        try {
            const d = await api(`/api/processes/get/${fileId}`);
            setYamlText(d.yaml);
            await loadFromYaml();
            setMeta(m => ({ ...m, id: fileId }));
            setStatusMsg(`已加载 ${fileId} ✓`);
        }
        catch (e) {
            setStatusMsg(`加载失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    async function refreshProcessList() {
        try {
            setProcessList(await api("/api/designer/list"));
        }
        catch { /* ignore */ }
    }
    useEffect(() => { void refreshProcessList(); }, []);
    // ---- 渲染 ----
    const stepRows = steps.map((s, i) => (_jsxs("div", { className: "flex gap-2 items-end flex-wrap border border-slate-100\n                 rounded-lg px-2 py-1.5 bg-slate-50 text-xs", children: [_jsxs("div", { className: "w-24", children: [_jsx("label", { className: "text-[10px] text-slate-300", children: "ID" }), _jsx("input", { className: "w-full px-1 py-0.5 text-xs border rounded", value: s.id, onChange: e => updateStep(i, { id: e.target.value }) })] }), _jsxs("div", { className: "flex-[2]", children: [_jsx("label", { className: "text-[10px] text-slate-300", children: "action" }), _jsx("input", { className: "w-full px-1 py-0.5 text-xs border rounded", value: s.action, onChange: e => updateStep(i, { action: e.target.value }) })] }), _jsxs("div", { className: "flex-[2]", children: [_jsx("label", { className: "text-[10px] text-slate-300", children: "condition" }), _jsx("input", { className: "w-full px-1 py-0.5 text-xs border rounded", value: s.condition, onChange: e => updateStep(i, { condition: e.target.value }) })] }), _jsx("button", { onClick: () => moveStep(i, -1), title: "\u4E0A\u79FB", children: "\u2191" }), _jsx("button", { onClick: () => moveStep(i, 1), title: "\u4E0B\u79FB", children: "\u2193" }), _jsx("button", { onClick: () => removeStep(i), className: "text-red-400 hover:text-red-600 px-1", children: "\u2715" })] }, s.id || i)));
    const processItems = processList.map(p => (_jsxs("div", { className: "flex items-center justify-between px-2 py-1 text-xs\n                    hover:bg-slate-50 rounded cursor-pointer", onClick: () => void openFile(p.id), children: [_jsx("span", { children: p.id }), _jsx("span", { className: p.valid ? "text-emerald-500" : "text-red-400", children: p.valid ? `${p.steps} 步骤` : p.error })] }, p.id)));
    return (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex gap-3 items-end flex-wrap", children: [_jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "\u6D41\u7A0B ID" }), _jsx("input", { className: "w-48 px-2 py-1 text-sm border rounded", value: meta.id, onChange: e => setMeta(m => ({ ...m, id: e.target.value })) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "\u89E6\u53D1\u4E8B\u4EF6" }), _jsx("input", { className: "w-64 px-2 py-1 text-sm border rounded", value: meta.trigger_name, onChange: e => setMeta(m => ({ ...m, trigger_name: e.target.value })) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-[11px] text-slate-400", children: "max_actions" }), _jsx("input", { className: "w-20 px-2 py-1 text-sm border rounded", type: "number", value: meta.max_actions, onChange: e => setMeta(m => ({ ...m, maxActions: +e.target.value || 50 })) })] }), _jsx("button", { onClick: () => void save(), className: "ml-auto px-4 py-1.5 text-sm font-semibold text-white\n                     bg-brand rounded-lg hover:bg-blue-700 transition-colors", children: "\uD83D\uDCBE \u4FDD\u5B58" })] }), _jsxs("div", { className: "grid grid-cols-[240px_1fr_280px] gap-3 items-start", children: [_jsx(CatalogPanel, {}), _jsxs("div", { className: "space-y-2 min-w-0", children: [_jsx("div", { style: { height: 420 }, className: "border border-slate-200 rounded-xl overflow-hidden", children: _jsxs(ReactFlow, { nodes: rfNodes, edges: rfEdges, onNodesChange: onNodesChange, onEdgesChange: onEdgesChange, nodeTypes: nodeTypes, fitView: true, children: [_jsx(Background, { variant: BackgroundVariant.Dots, gap: 16, size: 1 }), _jsx(Controls, {})] }) }), stepRows, _jsx("button", { onClick: addStep, className: "px-3 py-1 text-xs border border-dashed border-slate-300\n                       rounded-lg text-slate-500 hover:border-brand hover:text-brand\n                       transition-colors", children: "\uFF0B \u6DFB\u52A0\u6B65\u9AA4" }), _jsxs("details", { className: "mt-2", children: [_jsx("summary", { className: "text-xs text-slate-400 cursor-pointer", children: "YAML \u9884\u89C8 / \u624B\u52A8\u7F16\u8F91" }), _jsx("textarea", { className: "w-full mt-1 p-3 text-xs font-mono border rounded\n                         resize-y min-h-[200px]", rows: 14, value: yamlText, onChange: e => setYamlText(e.target.value) }), _jsx("button", { onClick: () => void syncToYaml(), className: "mr-1", children: "YAML \u2190 \u8868\u5355" }), _jsx("button", { onClick: () => void loadFromYaml(), className: "mt-1 px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "YAML \u2192 \u8868\u5355" })] })] }), _jsx("div", { className: "space-y-4", children: _jsx(TestRunPanelLazy, {}) })] }), _jsx("p", { className: "text-xs text-slate-500", children: statusMsg }), _jsxs("details", { className: "mt-2", children: [_jsxs("summary", { className: "text-xs text-slate-400 cursor-pointer", children: ["\u5DF2\u4FDD\u5B58\u6D41\u7A0B (", processList.filter(p => p.valid).length, ")"] }), _jsx("div", { className: "mt-1 space-y-1", children: processItems })] })] }));
    // --- 内部辅助 ---
    function TestRunPanelLazy() {
        return (_jsxs("div", { className: "space-y-2 p-1", children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase", children: "\u6C99\u76D2\u8BD5\u8FD0\u884C" }), _jsx("p", { className: "text-xs text-slate-400 p-2", children: "\u8BD5\u8FD0\u884C\u7531 M-B \u540E\u7EED\u8FED\u4EE3\u63D0\u4F9B\u5B8C\u6574 UI\uFF1B\u5F53\u524D\u901A\u8FC7 CLI \u89E6\u53D1" }), _jsx("button", { onClick: () => void syncToYaml(), className: "px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "\u540C\u6B65 YAML" })] }));
    }
    function CatalogPanel() {
        return (_jsxs("div", { className: "space-y-1", children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase", children: "\u52A8\u4F5C\u76EE\u5F55" }), _jsx("input", { className: "w-full px-2 py-1 text-xs border rounded", placeholder: "\u641C\u7D22\u52A8\u4F5C\u2026" }), _jsx("p", { className: "text-xs text-slate-400 p-2", children: "\u5B8C\u6574\u52A8\u4F5C\u76EE\u5F55\u9700\u63A5\u5165 /api/registry/actions\uFF08M-B \u540E\u7EED\u8FED\u4EE3\uFF09" })] }));
    }
}
