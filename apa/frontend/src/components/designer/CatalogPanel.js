import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "../../lib/utils";
/** 动作目录侧栏 —— 单一职责：展示+搜索+选中回调。 */
export function CatalogPanel({ onInsert }) {
    const [filter, setFilter] = useState("");
    const { data: catalog = {} } = useQuery({
        queryKey: ["registry", "actions"],
        queryFn: () => fetch("/api/registry/actions").then((r) => r.json()),
    });
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
    return (_jsxs("div", { className: "space-y-1", children: [_jsx("input", { className: "w-full px-2 py-1 text-xs border border-slate-200 rounded", placeholder: "\u641C\u7D22\u52A8\u4F5C\u2026", value: filter, onChange: (e) => setFilter(e.target.value) }), _jsxs("div", { className: "max-h-[400px] overflow-y-auto", children: [Object.entries(groups).map(([domain, items]) => (_jsxs("div", { children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase\n                          tracking-wide px-1 pt-2", children: domain }), items.map(([name, meta]) => (_jsxs("div", { onClick: () => onInsert(name), className: cn("px-2 py-1 cursor-pointer rounded text-xs hover:bg-blue-50", "flex justify-between items-center"), title: meta.description ?? "", children: [_jsx("span", { className: "font-mono truncate", children: name }), _jsx("span", { className: `text-[10px] rounded px-1 ${meta.risk.startsWith("L0") ? "text-slate-400"
                                            : meta.risk.startsWith("L1") || meta.risk.startsWith("L2")
                                                ? "text-amber-500" : "text-red-500"}`, children: meta.risk })] }, name)))] }, domain))), !Object.keys(groups).length && (_jsx("p", { className: "text-xs text-slate-400 p-2", children: "\uFF08\u65E0\u5339\u914D\u52A8\u4F5C\uFF09" }))] })] }));
}
