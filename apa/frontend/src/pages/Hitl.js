import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Hand } from "lucide-react";
import { Badge, Card, Button } from "../components/ui";
import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";
export function Hitl() {
    const qc = useQueryClient();
    const sessions = useSessions();
    const [resolving, setResolving] = useState(null);
    const [error, setError] = useState(null);
    const openTasks = Object.values(sessions.data ?? {}).flatMap((s) => s.tasks_open.map((t) => ({ ...t, session: s.id })));
    async function resolve(taskId, outcome) {
        setResolving(taskId);
        setError(null);
        try {
            await api(`/tasks/${taskId}/resolve`, {
                method: "POST",
                body: JSON.stringify({ outcome }),
            });
            await qc.invalidateQueries({ queryKey: ["sessions"] });
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            setResolving(null);
        }
    }
    return (_jsxs("div", { className: "space-y-4 max-w-4xl", children: [_jsxs("header", { className: "flex items-center gap-2.5", children: [_jsx(Hand, { size: 18, className: "text-amber-500" }), _jsx("h1", { className: "text-lg font-bold tracking-tight", children: "\u5BA1\u6279\u4E2D\u5FC3" }), openTasks.length > 0 && (_jsxs(Badge, { tone: "amber", children: [openTasks.length, " \u5F85\u5904\u7406"] }))] }), !openTasks.length ? (_jsxs(Card, { className: "p-10 text-center", children: [_jsx(Hand, { size: 32, className: "mx-auto text-slate-200 mb-3" }), _jsx("p", { className: "text-sm text-slate-500", children: "\u5F53\u524D\u65E0\u5F85\u5BA1\u6279\u4EFB\u52A1" }), _jsx("p", { className: "text-xs text-slate-300 mt-1", children: "\u5F53\u6D41\u7A0B\u89E6\u53D1 human.task.create \u6216 ui.confirm \u65F6\uFF0C \u5BA1\u6279\u5361\u7247\u5C06\u51FA\u73B0\u5728\u6B64\u5904" })] })) : (_jsx("div", { className: "space-y-2.5", children: openTasks.map((t) => (_jsx(Card, { className: "border-l-4 border-l-amber-400 px-4 py-3", children: _jsxs("div", { className: "flex items-start justify-between gap-3", children: [_jsxs("div", { className: "min-w-0", children: [_jsxs("div", { className: "flex items-center gap-2 flex-wrap", children: [_jsx(Badge, { tone: t.task_type === "confirm"
                                                    ? "blue" : "amber", children: t.task_type === "confirm" ? "确认" :
                                                    t.task_type === "exception" ? "异常" :
                                                        t.task_type }), _jsx("span", { className: "font-mono text-xs text-slate-600\n                                     truncate", children: t.task_id })] }), _jsxs("p", { className: "mt-0.5 text-[11px] text-slate-400 font-mono", children: ["\u4F1A\u8BDD ", t.session] })] }), _jsxs("div", { className: "flex gap-1.5 shrink-0", children: [_jsx(Button, { size: "sm", variant: "primary", disabled: resolving === t.task_id, onClick: () => void resolve(t.task_id, "approve"), children: "\u6279\u51C6" }), _jsx(Button, { size: "sm", variant: "danger", disabled: resolving === t.task_id, onClick: () => void resolve(t.task_id, "reject"), children: "\u9A73\u56DE" })] })] }) }, t.task_id))) })), error && _jsx("p", { className: "text-xs text-red-500", children: error })] }));
}
