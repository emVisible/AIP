import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * APA 低代码流程设计器 — Activity Pipeline Editor。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow, } from "@xyflow/react";
import { readDnDAction, readDnDStepIndex } from "./designerDnd";
import { api } from "../../api/client";
import { CatalogPanel } from "../../components/designer/CatalogPanel";
import { ParamsPanel } from "../../components/designer/ParamsPanel";
import { TestRunPanel } from "../../components/designer/TestRunPanel";
import { SpyPanel } from "../../components/designer/SpyPanel";
import { ScrapePanel } from "../../components/designer/ScrapePanel";
import "../../types/desktop";
function blankStep(i) {
    return {
        id: `step_${i + 1}`, type: "", action: "", target: "",
        params_json: "{}", condition: "", output_as: "",
        on_failure_goto: "",
    };
}
/** 按目录选择生成带模板参数的步骤（流程控制节点预填骨架）。 */
function stepFromAction(action, i) {
    const base = blankStep(i);
    if (action === "flow.foreach") {
        return { ...base, type: "foreach", id: `loop_${i + 1}`,
            params_json: JSON.stringify({
                source: "{{steps.extract_table.rows}}", item_var: "row",
                body_action: "", body_params: {},
            }, null, 2) };
    }
    if (action === "flow.sub_process") {
        return { ...base, type: "sub_process", id: `sub_${i + 1}`,
            params_json: JSON.stringify({
                process_id: "", input: {},
            }, null, 2) };
    }
    if (action === "flow.ai_decision") {
        return { ...base, type: "ai_decision", id: `decision_${i + 1}`,
            params_json: JSON.stringify({
                context: [], available_actions: [],
            }, null, 2) };
    }
    return { ...base, action };
}
function StepNodeView({ data }) {
    return (_jsxs("div", { className: `rounded-lg border-2 px-3 py-2 min-w-[150px] shadow-sm bg-white ${data.tone}`, children: [_jsx("p", { className: "text-xs font-semibold text-slate-700 truncate", children: data.label }), data.sub && (_jsx("p", { className: "text-[10px] text-slate-400 mt-0.5 truncate", children: data.sub }))] }));
}
const nodeTypes = { step: StepNodeView };
export function DesignerPage() {
    return (_jsx(ReactFlowProvider, { children: _jsx(DesignerInner, {}) }));
}
/** 内层：需要 useReactFlow 上下文。 */
function DesignerInner() {
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
    const [recording, setRecording] = useState(null);
    const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
    const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
    const { screenToFlowPosition } = useReactFlow();
    /** 新建节点的落点（画布流坐标），同步时优先于网格默认值。 */
    const dropPosRef = useRef(new Map());
    /** 步骤卡右键菜单状态。 */
    const [menu, setMenu] = useState(null);
    // steps → RF graph sync（保留用户拖动过的节点位置）
    useEffect(() => {
        const edges = [];
        for (let i = 0; i < steps.length - 1; i++) {
            edges.push({
                id: `e${i}`,
                source: steps[i]?.id ?? `n${i}`,
                target: steps[i + 1]?.id ?? `n${i + 1}`,
                animated: true,
            });
        }
        setRfNodes((prev) => {
            const prevPos = new Map(prev.map((n) => [n.id, n.position]));
            return steps.map((s2, i) => {
                const id = s2.id || `n${i}`;
                return {
                    id,
                    type: "step",
                    position: prevPos.get(id) ??
                        dropPosRef.current.get(id) ?? { x: 200, y: i * 100 },
                    data: {
                        label: s2.id || `step_${i + 1}`,
                        sub: s2.action || s2.type || "\u2014",
                        tone: selectedIdx === i
                            ? "border-blue-500 ring-2 ring-blue-200"
                            : s2.condition
                                ? "border-amber-300"
                                : "border-slate-300",
                    },
                };
            });
        });
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
    // ---- M4：画布拖放建节点 ---------------------------------------------------
    function handleCanvasDragOver(e) {
        if (e.dataTransfer.types.includes("application/apa-action")) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
        }
    }
    function handleCanvasDrop(e) {
        const action = readDnDAction(e.nativeEvent);
        if (!action)
            return;
        e.preventDefault();
        const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
        const step = stepFromAction(action, steps.length);
        dropPosRef.current.set(step.id, pos);
        setSelectedIdx(steps.length);
        setSteps((prev) => [...prev, step]);
        setStatusMsg(`已从目录拖入 ${action} ✓`);
    }
    // ---- M4：步骤卡排序 / 右键菜单 --------------------------------------------
    function moveStep(from, to) {
        if (from === to)
            return;
        setSteps((prev) => {
            if (from < 0 || from >= prev.length || to < 0 || to >= prev.length) {
                return prev;
            }
            const next = [...prev];
            const [moved] = next.splice(from, 1);
            next.splice(to, 0, moved);
            return next;
        });
        setSelectedIdx(to);
    }
    function handleCardDrop(target, e) {
        const from = readDnDStepIndex(e.nativeEvent);
        if (from === null) {
            // 目录动作落到步骤卡上 → 插到该卡之后
            const action = readDnDAction(e.nativeEvent);
            if (action)
                insertStep(target + 1, stepFromAction(action, target + 1));
            e.preventDefault();
            return;
        }
        e.preventDefault();
        moveStep(from, target);
    }
    function insertStep(at, step) {
        setSteps((prev) => {
            const at2 = Math.max(0, Math.min(at, prev.length));
            const next = [...prev.slice(0, at2), step, ...prev.slice(at2)];
            return next;
        });
        setSelectedIdx(at);
    }
    function duplicateStep(idx) {
        setSteps((prev) => {
            if (idx < 0 || idx >= prev.length)
                return prev;
            const src = prev[idx];
            const copy = { ...src,
                id: `${src.id || `step_${idx + 1}`}_copy${Date.now()
                    .toString(36).slice(-3)}` };
            return [...prev.slice(0, idx + 1), copy, ...prev.slice(idx + 1)];
        });
        setMenu(null);
    }
    function deleteStep(idx) {
        setSteps((prev) => prev.filter((_, i) => i !== idx));
        setSelectedIdx(null);
        setMenu(null);
    }
    function blankAt(at) {
        insertStep(at, blankStep(at));
        setMenu(null);
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
    async function importTemplate(t) {
        try {
            setYamlText(t.yaml);
            await loadFromYaml();
            setMetaId(`${t.id}_${Date.now().toString(36).slice(-4)}`);
            setCurrentFile("");
            setStatusMsg(`已从模板导入 ${t.name} ✓（记得另存）`);
        }
        catch (e) {
            setStatusMsg(`模板导入失败: ${e instanceof Error ? e.message : e}`);
        }
    }
    function addGeneratedSteps(steps, label) {
        setSteps(prev => {
            const converted = steps.map((raw, i) => {
                const { params, ...rest } = raw;
                return {
                    ...rest,
                    id: String(raw.id ?? `gen_${prev.length + i + 1}`),
                    type: String(raw.type ?? ""),
                    action: String(raw.action ?? ""),
                    target: "",
                    condition: "",
                    output_as: "",
                    on_failure_goto: "",
                    params_json: JSON.stringify(params ?? {}, null, 2),
                };
            });
            return [...prev, ...converted];
        });
        setStatusMsg(`抓取向导：已插入 ${label} ✓`);
    }
    function captureSpyElement(el) {
        setSteps(prev => {
            const step = {
                id: `spy_${prev.length + 1}`,
                type: "", action: "desktop.ui.click_element",
                target: "", condition: "", output_as: "",
                on_failure_goto: "",
                params_json: JSON.stringify({ element: el }, null, 2),
            };
            setSelectedIdx(prev.length);
            return [...prev, step];
        });
        setStatusMsg(`已捕获 ${el.app_name} · ${el.role}` +
            (el.title ? ` "${el.title.slice(0, 24)}"` : "") +
            " → 插入 click_element 步骤");
    }
    // ---- 浏览器录制 ----------------------------------------------------------
    function startRecording() {
        if (!recording || !recording.url.startsWith("http"))
            return;
        post("/api/recorder/start", { url: recording.url })
            .then((r) => {
            if (!r.session_id)
                throw new Error(r.detail ?? "启动失败");
            setRecording({ url: recording.url, events: 0,
                sid: r.session_id, phase: "running" });
            setStatusMsg("录制中：在打开的浏览器里操作…");
        })
            .catch((e) => setStatusMsg(`录制启动失败: ${e instanceof Error ? e.message : e}`));
    }
    function pollRecording(sid) {
        api(`/api/recorder/status/${sid}`)
            .then(st => setRecording(prev => prev
            ? { ...prev, events: st.events }
            : prev))
            .catch(() => { });
    }
    const recSid = recording?.phase === "running" ? recording.sid : null;
    useEffect(() => {
        if (!recSid)
            return;
        const t = setInterval(() => pollRecording(recSid), 1500);
        return () => clearInterval(t);
    }, [recSid]);
    function stopRecording() {
        if (!recording)
            return;
        post(`/api/recorder/stop/${recording.sid}`, { process_id: "recorded_flow" })
            .then(async (r) => {
            setRecording(null);
            if (r.yaml) {
                setYamlText(r.yaml);
                await loadFromYaml();
                setStatusMsg(`录制完成：${r.steps} 个步骤已导入画布 ✓`);
            }
            else {
                setStatusMsg("录制结束，但未捕获到任何操作");
            }
        })
            .catch((e) => {
            setRecording(null);
            setStatusMsg(`停止录制失败: ${e instanceof Error ? e.message : e}`);
        });
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
    return (_jsxs("div", { className: "h-full flex flex-col overflow-hidden", children: [_jsxs("div", { className: "flex items-center gap-3 px-4 py-2 border-b bg-white shadow-sm z-10", children: [_jsx("input", { className: "w-48 px-2 py-1 text-sm border rounded-md outline-none", placeholder: "\u6D41\u7A0B ID\u2026", value: metaId, onChange: e => setMetaId(e.target.value) }), _jsx("input", { className: "w-72 px-2 py-1 text-sm border rounded-md", placeholder: "\u89E6\u53D1\u4E8B\u4EF6\u2026", value: triggerName, onChange: e => setTriggerName(e.target.value) }), _jsx("input", { className: "w-20 px-2 py-1 text-sm border rounded", type: "number", value: maxActions, onChange: e => setMaxActions(+e.target.value || 50) }), _jsx("button", { className: "ml-auto px-4 py-1.5 text-xs font-semibold text-white bg-violet-600 rounded-md hover:bg-violet-700 transition-colors", onClick: () => setRecording({ sid: "", url: "https://",
                            events: 0, phase: "enter" }), children: "\uD83C\uDF99 \u5F55\u5236" }), _jsx("button", { className: "px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors", onClick: () => void save(), children: "\uD83D\uDCBE \u4FDD\u5B58" })] }), _jsxs("div", { className: "flex-1 grid grid-cols-[220px_1fr_260px] overflow-hidden", children: [_jsx("div", { className: "border-r p-3 overflow-y-auto bg-white", children: _jsx(CatalogPanel, { onInsert: (action) => {
                                setSteps(prev => [...prev, stepFromAction(action, prev.length)]);
                            } }) }), _jsxs("div", { className: "overflow-y-auto p-3", children: [_jsx("div", { style: { height: Math.max(280, rfNodes.length * 80 + 60) }, className: "border rounded-xl min-h-[250px] overflow-hidden", onDragOver: handleCanvasDragOver, onDrop: handleCanvasDrop, children: _jsxs(ReactFlow, { nodes: rfNodes, edges: rfEdges, onNodesChange: onNodesChange, onEdgesChange: onEdgesChange, nodeTypes: nodeTypes, fitView: true, children: [_jsx(Background, { variant: BackgroundVariant.Dots, gap: 20, size: 1.5, color: "#cbd5e1" }), _jsx(Controls, { showInteractive: false })] }) }), _jsx("div", { className: "mt-3 space-y-2", children: steps.map((s, i) => (_jsxs("div", { draggable: true, onDragStart: (e) => {
                                        e.dataTransfer.setData("application/apa-step-index", String(i));
                                        e.dataTransfer.effectAllowed = "move";
                                    }, onDragOver: (e) => {
                                        if (e.dataTransfer.types.includes("application/apa-step-index") ||
                                            e.dataTransfer.types.includes("application/apa-action")) {
                                            e.preventDefault();
                                        }
                                    }, onDrop: (e) => handleCardDrop(i, e), onClick: () => setSelectedIdx(i), onContextMenu: (e) => {
                                        e.preventDefault();
                                        setMenu({ idx: i, x: e.clientX, y: e.clientY });
                                    }, className: `cursor-grab active:cursor-grabbing rounded-lg
                            border px-3 py-2 text-xs ${selectedIdx === i
                                        ? "ring-1 ring-blue-300 border-blue-300 bg-blue-50"
                                        : "border-slate-200 bg-white"}`, children: [_jsxs("span", { className: "font-semibold mr-2", children: [i + 1, ". ", s.id] }), _jsx("span", { className: "text-slate-400 font-mono", children: s.action || (s.type ? `[${s.type}]` : "(未设置)") })] }, s.id || i))) }), _jsx("button", { onClick: () => setSteps(prev => [...prev, blankStep(prev.length)]), className: "w-full mt-2 py-2 text-xs border border-dashed border-slate-300\n                       rounded-lg text-slate-400 hover:border-blue-400 transition-colors", children: "\uFF0B \u6DFB\u52A0\u6B65\u9AA4" }), _jsxs("details", { className: "mt-4", children: [_jsx("summary", { className: "text-xs text-slate-400 cursor-pointer", children: "YAML" }), _jsx("textarea", { className: "w-full mt-1 p-2 text-xs font-mono border rounded resize-y min-h-[120px]", rows: 10, value: yamlText, onChange: e => setYamlText(e.target.value) }), _jsxs("div", { className: "flex gap-2 mt-1", children: [_jsx("button", { onClick: () => void syncToYaml(), className: "px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "\u8868\u5355 \u2192 YAML" }), _jsx("button", { onClick: () => void loadFromYaml(), className: "px-3 py-1 text-xs border rounded hover:bg-slate-50", children: "YAML \u2192 \u8868\u5355" })] })] })] }), _jsxs("div", { className: "border-l p-3 space-y-3 overflow-y-auto bg-white", children: [_jsx("p", { className: "text-xs font-semibold", children: "\u5C5E\u6027\u9762\u677F" }), _jsx(ParamsPanel, { steps: steps, selectedIdx: selectedIdx, onUpdate: updateStep, catalog: catalog }), selectedIdx != null && steps[selectedIdx] && (_jsxs("div", { className: "space-y-2 text-xs", children: [_jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "ID" }), _jsx("input", { className: "w-full px-2 py-1 border rounded mt-0.5", value: steps[selectedIdx]?.id ?? "", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, id: e.target.value } : s)) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "\u52A8\u4F5C\u540D" }), _jsx("input", { className: "w-full px-2 py-1 border rounded mt-0.5", value: steps[selectedIdx]?.action ?? "", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, action: e.target.value } : s)) })] }), _jsxs("div", { children: [_jsx("label", { className: "text-slate-400", children: "\u53C2\u6570 (JSON)" }), _jsx("textarea", { className: "w-full px-2 py-1 border rounded mt-0.5 font-mono", rows: 4, value: steps[selectedIdx]?.params_json ?? "{}", onChange: e => setSteps(prev => prev.map((s, j) => j === selectedIdx
                                                    ? { ...s, params_json: e.target.value } : s)) })] })] })), selectedIdx == null && (_jsx("p", { className: "text-xs text-slate-400 pt-2", children: "\u70B9\u51FB\u753B\u5E03\u4E2D\u7684\u8282\u70B9\u4EE5\u7F16\u8F91\u5C5E\u6027" })), _jsx(TestRunPanel, { yaml: yamlText }), _jsx(SpyPanel, { onCapture: captureSpyElement }), _jsx(ScrapePanel, { onGenerate: addGeneratedSteps }), _jsx(TemplateLibrary, { onPick: importTemplate }), _jsxs("details", { className: "mt-3", children: [_jsxs("summary", { className: "text-xs text-slate-400 cursor-pointer", children: ["\u5DF2\u4FDD\u5B58\u6D41\u7A0B (", processList.filter(p => p.valid).length, ")"] }), _jsxs("div", { className: "mt-1 space-y-0.5", children: [processList.map(p => (_jsxs("div", { onClick: () => void openFile(p.id), className: "flex items-center justify-between px-2 py-1 text-xs\n                                hover:bg-slate-50 rounded cursor-pointer", children: [_jsx("span", { className: "font-mono", children: p.id }), _jsx("span", { className: p.valid ? "text-emerald-500" : "text-red-400", children: p.valid ? `${p.steps} 步骤` : "\u26a0" })] }, p.id))), !processList.length && (_jsx("p", { className: "text-xs text-slate-300", children: "\uFF08\u6682\u65E0\uFF09" }))] })] })] })] }), _jsxs("div", { className: "px-4 py-1 bg-slate-900 text-slate-300 text-xs flex justify-between", children: [_jsx("span", { children: statusMsg }), _jsx("span", { children: currentFile })] }), menu && (_jsx("div", { className: "fixed inset-0 z-40", onClick: () => setMenu(null), onContextMenu: (e) => { e.preventDefault(); setMenu(null); }, children: _jsxs("div", { style: { left: menu.x, top: menu.y }, className: "absolute bg-white border border-slate-200\n                          rounded-lg shadow-lg py-1 w-36 text-xs", children: [_jsx("button", { onClick: () => duplicateStep(menu.idx), className: "w-full px-3 py-1.5 text-left hover:bg-slate-50", children: "\u29C9 \u590D\u5236\u6B65\u9AA4" }), _jsx("button", { onClick: () => blankAt(menu.idx), className: "w-full px-3 py-1.5 text-left hover:bg-slate-50", children: "\u2191 \u5728\u524D\u9762\u63D2\u5165" }), _jsx("button", { onClick: () => blankAt(menu.idx + 1), className: "w-full px-3 py-1.5 text-left hover:bg-slate-50", children: "\u2193 \u5728\u540E\u9762\u63D2\u5165" }), _jsx("div", { className: "my-0.5 border-t border-slate-100" }), _jsx("button", { onClick: () => deleteStep(menu.idx), className: "w-full px-3 py-1.5 text-left text-red-600\n                         hover:bg-red-50", children: "\u2715 \u5220\u9664\u6B65\u9AA4" })] }) })), recording && (_jsx("div", { className: "fixed inset-0 bg-black/40 flex items-center\n                        justify-center z-50", children: _jsxs("div", { className: "bg-white rounded-xl shadow-xl p-5 w-[380px]", children: [_jsx("p", { className: "text-sm font-semibold mb-3", children: "\uD83C\uDF99 \u6D4F\u89C8\u5668\u64CD\u4F5C\u5F55\u5236" }), recording.phase === "enter" ? (_jsxs(_Fragment, { children: [_jsx("input", { autoFocus: true, className: "w-full px-3 py-2 text-sm border rounded-md mb-3", placeholder: "\u8D77\u59CB URL\uFF08https://\u2026\uFF09", value: recording.url, onChange: e => setRecording({ ...recording,
                                        url: e.target.value }), onKeyDown: e => {
                                        if (e.key === "Enter")
                                            startRecording();
                                    } }), _jsxs("div", { className: "flex gap-2 justify-end", children: [_jsx("button", { onClick: () => setRecording(null), className: "px-3 py-1.5 text-xs border rounded-md\n                               hover:bg-slate-50", children: "\u53D6\u6D88" }), _jsx("button", { onClick: startRecording, className: "px-4 py-1.5 text-xs font-semibold text-white\n                               bg-violet-600 rounded-md hover:bg-violet-700", children: "\u5F00\u59CB\u5F55\u5236" })] })] })) : (_jsxs(_Fragment, { children: [_jsx("p", { className: "text-xs text-slate-500 mb-1", children: recording.url }), _jsxs("p", { className: "text-2xl font-bold text-violet-700 mb-3", children: ["\u5DF2\u6355\u83B7 ", recording.events, " \u4E2A\u4E8B\u4EF6", _jsx("span", { className: "ml-2 inline-block w-2 h-2 rounded-full\n                                   bg-red-500 animate-pulse align-middle" })] }), _jsx("p", { className: "text-xs text-slate-400 mb-4", children: "\u5728\u6253\u5F00\u7684\u6D4F\u89C8\u5668\u7A97\u53E3\u4E2D\u70B9\u51FB/\u8F93\u5165\uFF1B\u5B8C\u6210\u540E\u70B9\u300C\u505C\u6B62\u5E76\u5BFC\u5165\u300D\u3002" }), _jsxs("div", { className: "flex gap-2 justify-end", children: [_jsx("button", { onClick: () => setRecording(null), className: "px-3 py-1.5 text-xs border rounded-md\n                               hover:bg-slate-50", children: "\u540E\u53F0\u8FD0\u884C" }), _jsx("button", { onClick: stopRecording, className: "px-4 py-1.5 text-xs font-semibold text-white\n                               bg-red-600 rounded-md hover:bg-red-700", children: "\u25A0 \u505C\u6B62\u5E76\u5BFC\u5165" })] })] }))] }) }))] }));
}
function post(path, json) {
    return fetch(`/api${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(json),
    }).then(r => r.json());
}
/** 模板库侧栏：从 /api/templates 拉取，点击导入画布。 */
function TemplateLibrary({ onPick }) {
    const [open, setOpen] = useState(false);
    const [items, setItems] = useState([]);
    function toggle() {
        const next = !open;
        setOpen(next);
        if (next && !items.length) {
            api("/api/templates")
                .then(d => setItems(d.templates ?? []))
                .catch(() => { });
        }
    }
    return (_jsxs("details", { className: "mt-3", open: open, onToggle: (e) => {
            if (e.target.open !== open)
                toggle();
        }, children: [_jsx("summary", { className: "text-xs text-slate-400 cursor-pointer", children: "\u6A21\u677F\u5E93" }), _jsxs("div", { className: "mt-1 space-y-0.5", children: [items.map(t => (_jsxs("div", { onClick: () => void onPick(t), className: "px-2 py-1 text-xs hover:bg-violet-50 rounded\n                          cursor-pointer text-violet-700", children: ["\uD83D\uDCCB ", t.name] }, t.id))), !items.length && (_jsx("p", { className: "text-xs text-slate-300", children: "\uFF08\u52A0\u8F7D\u4E2D\u2026\uFF09" }))] })] }));
}
