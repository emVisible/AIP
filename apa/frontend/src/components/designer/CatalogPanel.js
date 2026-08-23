import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "../../lib/utils";
/** 流程控制特殊节点（非 registry 动作，由 ProcessEngine 内建解释）。 */
export const FLOW_NODES = [
    ["flow.foreach", "循环：遍历数组逐项执行 body_action"],
    ["flow.sub_process", "子流程：调用另一个 process.yaml"],
    ["flow.ai_decision", "AI 决策：LLM 从候选动作中选择 outcome"],
];
/** 动作目录侧栏 —— 单一职责：展示+搜索+选中回调。 */
export function CatalogPanel({ onInsert }) {
    const [filter, setFilter] = useState("");
    const { data: catalog = {} } = useQuery({
        queryKey: ["registry", "actions"],
        queryFn: () => fetch("/api/registry/actions").then((r) => r.json()),
    });
    const flowItems = useMemo(() => {
        const q = filter.toLowerCase();
        return FLOW_NODES.filter(([n, d]) => !q || n.toLowerCase().includes(q) || d.toLowerCase().includes(q));
    }, [filter]);
    const groups = useMemo(() => {
        const q = filter.toLowerCase();
        const byDomain = {};
        for (const [name, meta] of Object.entries(catalog)) {
            if (q && !name.toLowerCase().includes(q) &&
                !(meta.description ?? "").toLowerCase().includes(q)) {
                continue;
            }
            const domain = name.split(".")[0] ?? "other";
            (byDomain[domain] ??= []).push([name, meta]);
        }
        return byDomain;
    }, [catalog, filter]);
    return (_jsxs("div", { className: "space-y-1", children: [_jsx("input", { className: "w-full px-2 py-1 text-xs border border-slate-200 rounded", placeholder: "\u641C\u7D22\u52A8\u4F5C\u2026", value: filter, onChange: (e) => setFilter(e.target.value) }), _jsxs("div", { className: "max-h-[400px] overflow-y-auto", children: [flowItems.length > 0 && (_jsxs("div", { children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase\n                          tracking-wide px-1 pt-2", children: "\u6D41\u7A0B\u63A7\u5236" }), flowItems.map(([name, desc]) => (_jsxs("div", { draggable: true, onDragStart: (e) => {
                                    e.dataTransfer.setData("application/apa-action", name);
                                    e.dataTransfer.effectAllowed = "copy";
                                }, onClick: () => onInsert(name), className: "px-2 py-1 cursor-pointer rounded text-xs\n                           hover:bg-violet-50 flex justify-between items-center", title: desc, children: [_jsx("span", { className: "font-mono truncate text-violet-700", children: name }), _jsx("span", { className: "text-[10px] rounded px-1 bg-violet-100\n                                 text-violet-600", children: "CTL" })] }, name)))] })), Object.entries(groups).map(([domain, items]) => (_jsxs("div", { children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase\n                          tracking-wide px-1 pt-2", children: domain }), items.map(([name, meta]) => (_jsxs("div", { draggable: true, onDragStart: (e) => {
                                    e.dataTransfer.setData("application/apa-action", name);
                                    e.dataTransfer.effectAllowed = "copy";
                                }, onClick: () => onInsert(name), className: cn("px-2 py-1 cursor-pointer rounded text-xs hover:bg-blue-50", "flex justify-between items-center"), title: meta.description ?? "", children: [_jsx("span", { className: "font-mono truncate", children: name }), _jsx("span", { className: `text-[10px] rounded px-1 ${meta.risk.startsWith("L0") ? "text-slate-400"
                                            : meta.risk.startsWith("L1") || meta.risk.startsWith("L2")
                                                ? "text-amber-500" : "text-red-500"}`, children: meta.risk })] }, name)))] }, domain))), !Object.keys(groups).length && (_jsx("p", { className: "text-xs text-slate-400 p-2", children: "\uFF08\u65E0\u5339\u914D\u52A8\u4F5C\uFF09" }))] })] }));
}
