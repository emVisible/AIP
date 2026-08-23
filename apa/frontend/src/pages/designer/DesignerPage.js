import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * APA 低代码流程设计器 — Activity Pipeline Editor。
 */
import { useCallback, useEffect, useState } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, useEdgesState, useNodesState, } from "@xyflow/react";
import { api } from "../../api/client";
import { CatalogPanel } from "../../components/designer/CatalogPanel";
import { ParamsPanel } from "../../components/designer/ParamsPanel";
import { TestRunPanel } from "../../components/designer/TestRunPanel";
function blankStep(i) {
    return {
        id: `step_${i + 1}`, type: "", action: "", target: "",
        params_json: "{}", condition: "", output_as: "",
        on_failure_goto: "",
    };
}
function StepNodeView({ data }) {
    return (_jsxs("div", { className: `rounded-lg border-2 px-3 py-2 min-w-[150px] shadow-sm bg-white ${data.tone}`, children: [_jsx("p", { className: "text-xs font-semibold text-slate-700 truncate", children: data.label }), data.sub && (_jsx("p", { className: "text-[10px] text-slate-400 mt-0.5 truncate", children: data.sub }))] }));
}
const nodeTypes = { step: StepNodeView };
export function DesignerPage() {
    const [metaId, setMetaId] = useState("");
    const [triggerName, setTriggerName] = useState("");
    const [maxActions, setMaxActions] = useState(50);
    const [steps, setSteps] = useState([blankStep(0)]);
    const [selectedIdx, setSelectedIdx] = useState(null);
    const [yamlText, setYamlText] = useState("");
    const [statusMsg, setStatusMsg] = useState("就绪");
    const [processList, setProcessList] = useState([]);
    const [catalog, setCatalog] = useState({});
    const [currentFile, setCurrentFile] = useState("");
    const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
    const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
    // steps → RF graph sync
    useEffect(() => {
        const nodes = steps.map((s, i) => ({
            id: s.id || `n${i}`,
            type: "step",
            position: { x: 200, y: i * 100 },
            data: {
                label: s.id || `step_${i + 1}`,
                sub: s.action || s.type || "\u2014",
                tone: selectedIdx === i
                    ? "border-blue-500 ring-2 ring-blue-200"
                    : s.condition
                        ? "border-amber-300"
                        : "border-slate-300",
            },
        }));
        const edges = [];
        for (let i = 0; i < steps.length - 1; i++) {
            edges.push({
                id: `e${i}`,
                source: steps[i]?.id ?? `n${i}`,
                target: steps[i + 1]?.id ?? `n${i + 1}`,
                animated: true,
            });
        }
        setRfNodes(nodes);
        setRfEdges(edges);
    }, [steps, selectedIdx, setRfNodes, setRfEdges]);
    // 数据加载
    useEffect(() => {
        api("/api/processes").then(setProcessList).catch(() => { });
        api("/api/registry/actions")
            .then(setCatalog)
            .catch(() => { });
    }, []);
    const updateStep = useCallback((i, patch) => setSteps(prev => prev.map((s, j) => (j === i ? { ...s, ...patch } : s))), []);
    function buildForm() {
        return {
            id: metaId,
            trigger_name: triggerName,
            max_actions: maxActions,
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
            const form = buildForm();
            const d = await api("/api/processes/from-form", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ form }),
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
            const d = await api("/api/processes/to-form", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ yaml: yamlText }),
            });
            setMetaId(d.form.id);
            setTriggerName(d.form.trigger_name);
            setMaxActions(d.form.max_actions);
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
            await post("/api/processes/save", {
                id: metaId || "untitled", yaml: yamlText || "{}",
            });
            setStatusMsg(`已保存 ${metaId} ✓`);
            void refreshProcessList();
        }
        catch (e) {
            setStatusMsg(`保存失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    function refreshProcessList() {
        api("/api/processes").then(setProcessList).catch(() => { });
    }
    async function openFile(fileId) {
        try {
            const d = await api(`/api/processes/get/${fileId}`);
            setYamlText(d.yaml);
            await loadFromYaml();
            setMetaId(fileId);
            setCurrentFile(fileId);
            setStatusMsg(`已加载 ${fileId} ✓`);
        }
        catch (e) {
            setStatusMsg(`加载失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    return (_jsxs("div", { className: "h-full flex flex-col overflow-hidden", children: [_jsxs("div", { className: "flex items-center gap-3 px-4 py-2 border-b bg-white shadow-sm z-10", children: [_jsx("input", { className: "w-48 px-2 py-1 text-sm border rounded-md outline-none", placeholder: "\u6D41\u7A0B ID\u2026", value: metaId, onChange: e => setMetaId(e.target.value) }), _jsx("input", { className: "w-72 px-2 py-1 text-sm border rounded-md", placeholder: "\u89E6\u53D1\u4E8B\u4EF6\u2026", value: triggerName, onChange: e => setTriggerName(e.target.value) }), _jsx("input", { className: "w-20 px-2 py-1 text-sm border rounded", type: "number", value: maxActions, onChange: e => setMaxActions(+e.target.value || 50) }), _jsx("button", { className: "ml-auto px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors", onClick: () => void save(), children: "\uD83D\uDCBE \u4FDD\u5B58" })] }), _jsxs("div", { className: "flex-1 grid grid-cols-[220px_1fr_260px] overflow-hidden", children: [_jsx("div", { className: "border-r p-3 overflow-y-auto bg-white", children: _jsx(CatalogPanel, { onInsert: (_action) => {
                                setSteps(prev => [...prev, blankStep(prev.length)]);
                            } }) }), _jsxs("div", { className: "overflow-y-auto p-3", children: [_jsx("div", { style: { height: Math.max(280, rfNodes.length * 80 + 60) }, className: "border rounded-xl min-h-[250px] overflow-hidden", children: _jsxs(ReactFlow, { nodes: rfNodes, edges: rfEdges, onNodesChange: onNodesChange, onEdgesChange: onEdgesChange, nodeTypes: nodeTypes, fitView: true, children: [_jsx(Background, { variant: BackgroundVariant.Dots, gap: 20, size: 1.5, color: "#cbd5e1" }), _jsx(Controls, { showInteractive: false })] }) }), _jsx("div", { className: "mt-3 space-y-2", children: steps.map((s, i) => (_jsxs("div", { onClick: () => setSelectedIdx(i), className: `cursor-pointer rounded-lg border px-3 py-2 text-xs ${selectedIdx === i
                                        ? "ring-1 ring-blue-300 border-blue-300 bg-blue-50"
                                        : "border-slate-200 bg-white"}`, children: [_jsxs("span", { className: "font-semibold mr-2", children: [i + 1, ". ", s.id] }), _jsx("span", { className: "text-slate-400 font-mono", children: s.action || "(未设置)" })] }, s.id || i))) }), _jsx("button", { onClick: () => setSteps(prev => [...prev, blankStep(prev.length)]), className: "w-full mt-2 py-2 text-xs border border-dashed border-slate-300\n                       rounded-lg text-slate-400 hover:border-blue-400 transition-colors", children: "\uFF0B \u6DFB\u52A0\u6B65\u9AA4" }), _jsxs("details", { className: "mt-4", children: [_jsx("summary", { className: "text-xs text-slate-400 cursor-pointer", children: "YAML" }), _jsx("textarea", { className: "w-full mt-1 p-2 text-xs font-mono border rounded resize-y min-h-[120px]", rows: 10, value: yamlText, onChange: e => setYamlText(e.target.value) }), _jsxs("div", { className: "flex gap-2 mt-1", children: [_jsx("button", { onClick: () => void syncToYaml(), className: "px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "\u8868\u5355 \u2192 YAML" }), _jsx("button", { onClick: () => void loadFromYaml(), className: "px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "YAML \u2192 \u8868\u5355" })] })] })] }), _jsxs("div", { className: "border-l p-3 space-y-3 overflow-y-auto bg-white", children: [_jsx("p", { className: "text-xs font-semibold", children: "\u5C5E\u6027\u9762\u677F" }), _jsx(ParamsPanel, { steps: steps, selectedIdx: selectedIdx, onUpdate: updateStep, catalog: catalog }), selectedIdx != null && steps[selectedIdx] && (_jsxs("div", { className: "space-y-2 text-xs", children: [_jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "ID" }), _jsx("input", { className: "w-full px-2 py-1 border rounded mt-0.5", value: steps[selectedIdx]?.id ?? "", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, id: e.target.value } : s)) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "\u52A8\u4F5C\u540D" }), _jsx("input", { className: "w-full px-2 py-1 border rounded mt-0.5", value: steps[selectedIdx]?.action ?? "", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, action: e.target.value } : s)) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "\u53C2\u6570 (JSON)" }), _jsx("textarea", { className: "w-full px-2 py-1 border rounded mt-0.5 font-mono", rows: 4, value: steps[selectedIdx]?.params_json ?? "{}", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, params_json: e.target.value } : s)) })] })] })), selectedIdx == null && (_jsx("p", { className: "text-xs text-slate-400 pt-2", children: "\u70B9\u51FB\u753B\u5E03\u4E2D\u7684\u8282\u70B9\u4EE5\u7F16\u8F91\u5C5E\u6027" })), _jsx(TestRunPanel, { yaml: yamlText }), _jsxs("details", { className: "mt-3", children: [_jsxs("summary", { className: "text-xs text-slate-400 cursor-pointer", children: ["\u5DF2\u4FDD\u5B58\u6D41\u7A0B (", processList.filter(p => p.valid).length, ")"] }), _jsxs("div", { className: "mt-1 space-y-0.5", children: [processList.map(p => (_jsxs("div", { onClick: () => void openFile(p.id), className: "flex items-center justify-between px-2 py-1 text-xs\n                                hover:bg-slate-50 rounded cursor-pointer", children: [_jsx("span", { className: "font-mono", children: p.id }), _jsx("span", { className: p.valid ? "text-emerald-500" : "text-red-400", children: p.valid ? `${p.steps} 步骤` : "\u26a0" })] }, p.id))), !processList.length && (_jsx("p", { className: "text-xs text-slate-300", children: "\uFF08\u6682\u65E0\uFF09" }))] })] })] })] }), _jsxs("div", { className: "px-4 py-1 bg-slate-900 text-slate-300 text-xs flex justify-between", children: [_jsx("span", { children: statusMsg }), _jsx("span", { children: currentFile })] })] }));
}
function post(path, json) {
    return fetch(`/api${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(json),
    }).then(r => r.json());
}
