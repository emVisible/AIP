import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, CircleCheck, Clock, Hand } from "lucide-react";
import { Badge } from "../components/ui/primitives";
import { useAnalytics, useSessions, } from "../hooks/useSessions";
import { useJournalStream } from "../hooks/useJournalStream";
import { stateTone } from "../lib/utils";
import { cn } from "../lib/utils";
function StatCard({ icon: Icon, label, value }) {
    return (_jsxs("div", { className: "flex items-center gap-3 rounded-xl border border-slate-200\n                    bg-surface px-4 py-3 shadow-sm", children: [_jsx(Icon, { size: 20, className: "text-brand" }), _jsxs("div", { children: [_jsx("p", { className: "text-xs text-slate-400", children: label }), _jsx("p", { className: "text-lg font-semibold leading-tight", children: value })] })] }));
}
export function Dashboard() {
    const qc = useQueryClient();
    const sessions = useSessions();
    const analytics = useAnalytics();
    // SSE 实时流：journal 增量 → 失效 Query 触发刷新（单一职责：hook 只管流）
    const feed = [];
    useJournalStream((record) => {
        qc.invalidateQueries({ queryKey: ["sessions"] });
        qc.invalidateQueries({ queryKey: ["analytics"] });
        feed.unshift(record);
        if (feed.length > 60)
            feed.pop();
    });
    const a = analytics.data;
    const rate = a?.actions.success_rate;
    const list = Object.values(sessions.data ?? {}).sort((x, y) => y.last_ts - x.last_ts);
    return (_jsxs("div", { className: "space-y-5 max-w-6xl", children: [_jsx("h1", { className: "text-xl font-bold", children: "\u76D1\u63A7\u603B\u89C8" }), _jsxs("div", { className: "grid grid-cols-4 gap-4", children: [_jsx(StatCard, { icon: Activity, label: "\u4F1A\u8BDD\u603B\u6570", value: String(a?.sessions.total ?? "—") }), _jsx(StatCard, { icon: CircleCheck, label: "\u52A8\u4F5C\u6210\u529F\u7387", value: rate != null ? `${(rate * 100).toFixed(0)}%` : "—" }), _jsx(StatCard, { icon: Clock, label: "\u8017\u65F6 p50", value: a?.actions.duration_ms.p50 != null
                            ? `${a.actions.duration_ms.p50}ms` : "—" }), _jsx(StatCard, { icon: Hand, label: "\u5F85\u5BA1\u6279\u4EFB\u52A1", value: String(a?.human_tasks.open ?? 0) })] }), _jsxs("div", { className: "grid grid-cols-[1fr_320px] gap-4 items-start", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-sm font-semibold mb-2 text-slate-500", children: "\u4F1A\u8BDD" }), _jsxs("div", { className: "space-y-2", children: [list.map((s) => (_jsxs("div", { className: "flex items-center justify-between rounded-lg border\n                           border-slate-200 bg-surface px-4 py-2.5 text-sm", children: [_jsx("span", { className: "font-mono text-xs", children: s.id }), _jsx(Badge, { tone: stateTone(s.state), children: s.state }), _jsxs("span", { className: "text-xs text-slate-400", children: ["\u6E38\u6807 ", Object.entries(s.cursors).map(([k, v]) => `${k}:${v}`).join(" ") || "—"] }), _jsx("span", { className: "text-xs text-slate-400", children: s.journal })] }, s.id))), !list.length && (_jsx("p", { className: "text-sm text-slate-400 py-8 text-center", children: "\u6682\u65E0\u4F1A\u8BDD \u2014\u2014 \u8FD0\u884C\u793A\u4F8B\u6216\u7B49\u5F85\u8C03\u5EA6\u5668\u89E6\u53D1" }))] })] }), _jsxs("div", { children: [_jsx("h2", { className: "text-sm font-semibold mb-2 text-slate-500", children: "\u5B9E\u65F6\u4E8B\u4EF6\u6D41" }), _jsxs("div", { className: cn("rounded-xl border border-slate-200 bg-surface divide-y divide-slate-50", "max-h-[420px] overflow-y-auto"), children: [feed.length === 0 && (_jsx("p", { className: "text-xs text-slate-400 p-3", children: "\uFF08\u7B49\u5F85\u4E8B\u4EF6\u2026\uFF09" })), feed.map((r, i) => (_jsxs("div", { className: "px-3 py-1.5 flex items-center gap-2 text-xs", children: [_jsx(Badge, { tone: stateTone(""), children: r.kind }), _jsx("span", { className: "font-mono truncate flex-1", children: r.name ?? r.status ?? r.to ?? r.task_id ?? "" })] }, i)))] })] })] })] }));
}
