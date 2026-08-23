import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";
export function Hitl() {
    const qc = useQueryClient();
    const sessions = useSessions();
    const [resolving, setResolving] = useState(null);
    const openTasks = Object.values(sessions.data ?? {}).flatMap(s => s.tasks_open.map(t => ({ ...t, session: s.id })));
    async function resolve(taskId, outcome) {
        setResolving(taskId);
        try {
            await api(`/tasks/${taskId}/resolve`, {
                method: "POST", body: JSON.stringify({ outcome }),
            });
            await qc.invalidateQueries({ queryKey: ["sessions"] });
        }
        catch (e) {
            console.error("resolve failed:", e);
        }
        finally {
            setResolving(null);
        }
    }
    return (_jsxs("div", { className: "space-y-4 max-w-4xl", children: [_jsx("h1", { className: "text-xl font-bold", children: "\u5BA1\u6279\u4E2D\u5FC3" }), !openTasks.length && (_jsxs("div", { className: "rounded-xl border border-slate-200 bg-surface\n                        p-8 text-center", children: [_jsx("p", { className: "text-sm text-slate-400", children: "\u5F53\u524D\u65E0\u5F85\u5BA1\u6279\u4EFB\u52A1" }), _jsx("p", { className: "text-xs text-slate-300 mt-1", children: "\u5F53\u6D41\u7A0B\u89E6\u53D1 human.task.create \u65F6\uFF0C\u4EFB\u52A1\u5C06\u51FA\u73B0\u5728\u6B64\u5904" })] })), openTasks.map(t => (_jsxs("div", { className: "flex items-center justify-between rounded-xl\n                     border border-amber-200 bg-amber-50 px-4 py-3", children: [_jsxs("div", { children: [_jsx("p", { className: "text-sm font-medium", children: t.task_id }), _jsxs("p", { className: "text-xs text-slate-500", children: ["\u7C7B\u578B: ", t.task_type, " \u00B7 \u4F1A\u8BDD: ", t.session] })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { disabled: resolving === t.task_id, onClick: () => void resolve(t.task_id, "approve"), className: "px-3 py-1.5 text-xs font-semibold text-white\n                         bg-emerald-600 rounded hover:bg-emerald-700\n                         disabled:opacity-50 transition-colors", children: "\u6279\u51C6" }), _jsx("button", { disabled: resolving === t.task_id, onClick: () => void resolve(t.task_id, "reject"), className: "px-3 py-1.5 text-xs font-semibold text-white\n                         bg-red-500 rounded hover:bg-red-600\n                         disabled:opacity-50 transition-colors", children: "\u9A73\u56DE" })] })] }, t.task_id)))] }));
}
