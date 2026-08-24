import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Badge, Card, CardHeader } from "../components/ui";
export function Settings() {
    const [actions, setActions] = useState({});
    const [filter, setFilter] = useState("");
    useEffect(() => {
        fetch("/api/registry/actions")
            .then(r => r.json())
            .then(setActions)
            .catch(() => { });
    }, []);
    const filtered = Object.entries(actions).filter(([name]) => !filter || name.toLowerCase().includes(filter.toLowerCase()));
    return (_jsxs("div", { className: "space-y-4 max-w-4xl", children: [_jsx("h1", { className: "text-xl font-bold", children: "\u8BBE\u7F6E" }), _jsxs(Card, { children: [_jsx(CardHeader, { title: "\u51B3\u7B56\u5F15\u64CE" }), _jsx(EnginePanel, {})] }), _jsxs("div", { className: "rounded-xl border border-slate-200 bg-surface overflow-hidden", children: [_jsxs("div", { className: "px-4 py-3 border-b border-slate-100 flex items-center\n                        justify-between", children: [_jsxs("h2", { className: "text-sm font-semibold", children: ["Action Registry\uFF08", Object.keys(actions).length, " \u4E2A\u52A8\u4F5C\uFF09"] }), _jsx("input", { className: "w-48 px-2 py-1 text-xs border rounded", placeholder: "\u641C\u7D22\u2026", value: filter, onChange: e => setFilter(e.target.value) })] }), _jsxs("table", { className: "w-full text-xs", children: [_jsx("thead", { children: _jsxs("tr", { className: "border-b border-slate-100 bg-slate-50 text-left\n                           text-slate-500", children: [_jsx("th", { className: "px-4 py-2 font-medium", children: "\u52A8\u4F5C\u540D" }), _jsx("th", { className: "px-4 py-2 font-medium", children: "\u98CE\u9669" }), _jsx("th", { className: "px-4 py-2 font-medium", children: "\u57DF" }), _jsx("th", { className: "px-4 py-2 font-medium", children: "\u5E42\u7B49\u6027" }), _jsx("th", { className: "px-4 py-2 font-medium", children: "\u63CF\u8FF0" })] }) }), _jsx("tbody", { children: filtered.map(([name, meta]) => (_jsxs("tr", { className: "border-b border-slate-50 hover:bg-slate-50", children: [_jsx("td", { className: "px-4 py-1.5 font-mono", children: name }), _jsx("td", { className: "px-4 py-1.5", children: _jsx("span", { className: `rounded px-1.5 ${meta.risk.startsWith("L0") ? "bg-emerald-50 text-emerald-600"
                                                    : meta.risk.startsWith("L1") ? "bg-blue-50 text-blue-600"
                                                        : meta.risk.startsWith("L2") ? "bg-amber-50 text-amber-600"
                                                            : "bg-red-50 text-red-600"}`, children: meta.risk }) }), _jsx("td", { className: "px-4 py-1.5", children: meta.executor_domain }), _jsx("td", { className: "px-4 py-1.5", children: meta.idempotency }), _jsx("td", { className: "px-4 py-1.5 text-slate-400", children: meta.description.slice(0, 40) })] }, name))) })] })] }), _jsxs("div", { className: "rounded-xl border border-slate-200 bg-surface p-4 space-y-2", children: [_jsx("h2", { className: "text-sm font-semibold", children: "\u79DF\u6237\u4E0E\u8BA4\u8BC1" }), _jsx("p", { className: "text-xs text-slate-400", children: "\u591A\u79DF\u6237\u7BA1\u7406\u4E0E\u8BA4\u8BC1\u914D\u7F6E\u5C06\u5728 M3 \u4EA7\u54C1\u5316\u9636\u6BB5\u63D0\u4F9B\u5B8C\u6574 UI\u3002" })] })] }));
}
/** 决策引擎状态与配置引导（只读；密钥仅经环境变量/.env 注入）。 */
function EnginePanel() {
    const [st, setSt] = useState(null);
    useEffect(() => {
        fetch("/api/ai/status")
            .then((r) => r.json())
            .then(setSt)
            .catch(() => { });
    }, []);
    const mode = st?.mode ?? "unknown";
    const tone = mode === "dsh" ? "green"
        : mode === "cascade_llm" ? "blue" : "neutral";
    const label = mode === "dsh" ? "DSH 已接入"
        : mode === "cascade_llm" ? "级联决策 (L0 规则 + LLM)"
            : mode === "rules_only" ? "仅规则 (L0)" : mode;
    return (_jsxs("div", { className: "px-3 py-3 space-y-2 text-xs", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("span", { className: "text-slate-500", children: "\u5F53\u524D\u6A21\u5F0F" }), _jsx(Badge, { tone: tone, children: label }), st?.model && (_jsx("span", { className: "font-mono text-[10px] text-slate-400", children: st.model }))] }), _jsxs("p", { className: "text-[11px] leading-relaxed text-slate-400", children: ["\u542F\u7528 LLM \u51B3\u7B56\uFF1A\u8BBE\u7F6E\u73AF\u5883\u53D8\u91CF ", _jsx("code", { className: "font-mono", children: "DEEPSEEK_API_KEY" }), " ", "\uFF08\u53EF\u9009 ", _jsx("code", { className: "font-mono", children: "DEEPSEEK_MODEL" }), "\uFF0C \u9ED8\u8BA4 deepseek-chat\uFF09\u540E\u91CD\u542F\u670D\u52A1\u3002 \u65E0\u5BC6\u94A5\u65F6 ai_decision \u8282\u70B9\u81EA\u52A8\u8F6C\u4EBA\u5DE5\u5BA1\u6279\uFF0C\u5168\u90E8\u529F\u80FD\u79BB\u7EBF\u53EF\u7528\u3002"] }), _jsxs("p", { className: "text-[11px] leading-relaxed text-slate-400", children: ["\u5916\u90E8 DSH \u5BBF\u4E3B\uFF1A", _jsx("code", { className: "font-mono", children: "node plugins/dsh/run-agent.mjs --gateway ws://127.0.0.1:8765 --session <\u4F1A\u8BDD> --mock" })] })] }));
}
