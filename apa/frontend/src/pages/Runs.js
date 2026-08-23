import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Badge } from "../components/ui/primitives";
import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";
import { stateTone } from "../lib/utils";
export function Runs() {
    const sessions = useSessions();
    const [expanded, setExpanded] = useState(null);
    const [details, setDetails] = useState({});
    async function toggleDetail(sid) {
        if (expanded === sid) {
            setExpanded(null);
            return;
        }
        setExpanded(sid);
        try {
            // POC：复用 sessions 数据展开（完整 journal 查询为 M2 增强）
            const recs = await api(`/api/journal/records?session=${sid}`);
            setDetails(prev => ({ ...prev, [sid]: { session: sid, records: recs } }));
        }
        catch {
            setDetails(prev => ({ ...prev, [sid]: {
                    session: sid, records: [{ info: "详细轨迹查询为 M2 增强" }]
                } }));
        }
    }
    const list = Object.values(sessions.data ?? {})
        .sort((a, b) => b.last_ts - a.last_ts);
    return (_jsxs("div", { className: "space-y-4 max-w-6xl", children: [_jsx("h1", { className: "text-xl font-bold", children: "\u8FD0\u884C\u5386\u53F2" }), !list.length && (_jsx("p", { className: "text-sm text-slate-400 py-8 text-center", children: "\u6682\u65E0\u8FD0\u884C\u8BB0\u5F55" })), _jsx("div", { className: "space-y-3", children: list.map(s => (_jsxs("div", { className: "rounded-xl border border-slate-200 bg-surface shadow-sm\n                       overflow-hidden", children: [_jsxs("div", { className: "flex items-center justify-between px-4 py-3 cursor-pointer\n                         hover:bg-slate-50 transition-colors", onClick: () => void toggleDetail(s.id), children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx(Badge, { tone: stateTone(s.state), children: s.state }), _jsx("span", { className: "font-mono text-sm", children: s.id }), s.outcome && (_jsxs("span", { className: "text-xs text-slate-400", children: ["\u2192 ", s.outcome] }))] }), _jsxs("div", { className: "flex items-center gap-4 text-xs text-slate-400", children: [_jsxs("span", { children: ["\u6E38\u6807: ", Object.entries(s.cursors)
                                                    .map(([k, v]) => `${k}:${v}`).join(" ") || "—"] }), s.tenant && _jsx("span", { className: "rounded bg-slate-100 px-1.5", children: s.tenant })] })] }), expanded === s.id && details[s.id] && (_jsxs("div", { className: "border-t border-slate-100 px-4 py-3 bg-slate-50", children: [_jsx("p", { className: "text-[10px] text-slate-400 uppercase mb-1", children: "Journal Records" }), _jsxs("div", { className: "space-y-1 max-h-[300px] overflow-y-auto", children: [(details[s.id]?.records ?? []).map((rec, i) => (_jsxs("div", { className: "flex items-center gap-2 text-xs\n                                            font-mono text-slate-600", children: [_jsx("span", { className: "text-slate-300", children: String(rec.kind) }), _jsx("span", { children: String(rec.to ?? rec.status ??
                                                        rec.name ?? "") })] }, i))), !(details[s.id]?.records ?? []).length && (_jsx("p", { className: "text-xs text-slate-400", children: "\uFF08\u65E0\u8BB0\u5F55\uFF09" }))] })] }))] }, s.id))) })] }));
}
