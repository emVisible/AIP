import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
export function Assistant() {
    const [status, setStatus] = useState(null);
    const [loaded, setLoaded] = useState(false);
    useEffect(() => {
        fetch("/api/ai/status")
            .then(r => r.json())
            .then(d => { setStatus(d); setLoaded(true); })
            .catch(() => setLoaded(true));
    }, []);
    return (_jsxs("div", { className: "space-y-4 max-w-2xl", children: [_jsx("h1", { className: "text-xl font-bold", children: "AI \u52A9\u624B" }), !loaded ? (_jsx("p", { className: "text-sm text-slate-400", children: "\u52A0\u8F7D\u4E2D\u2026" })) : (_jsxs("div", { className: "rounded-xl border border-slate-200 bg-surface p-5\n                        space-y-3", children: [_jsx("h2", { className: "text-sm font-semibold", children: "\u51B3\u7B56\u5F15\u64CE\u914D\u7F6E\u72B6\u6001" }), _jsxs("dl", { className: "space-y-2 text-sm", children: [_jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "\u6A21\u5F0F" }), _jsx("dd", { className: "font-medium", children: status?.mode ?? "rules_only" })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "\u6A21\u578B" }), _jsx("dd", { className: "font-mono text-xs", children: status?.model ?? "deepseek-chat" })] }), _jsxs("div", { className: "flex justify-between", children: [_jsx("dt", { className: "text-slate-500", children: "API Key" }), _jsx("dd", { children: status?.key_configured
                                            ? _jsx("span", { className: "text-emerald-600", children: "\u2713 \u5DF2\u914D\u7F6E" })
                                            : _jsx("span", { className: "text-amber-500", children: "\u2717 \u672A\u914D\u7F6E" }) })] })] }), !status?.key_configured && (_jsxs("div", { className: "mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200\n                            space-y-1", children: [_jsx("p", { className: "text-xs font-semibold text-amber-700", children: "\u542F\u7528 LLM \u51B3\u7B56\u7EA7\u8054\uFF08\u00A77.2 L1/L2\uFF09" }), _jsxs("p", { className: "text-xs text-amber-600 leading-relaxed", children: ["\u7F16\u8F91\u4ED3\u5E93\u6839\u76EE\u5F55\u7684 ", _jsx("code", { className: "font-mono bg-amber-100 px-1 rounded", children: ".env" }), " \u6587\u4EF6\uFF1A", _jsx("br", {}), "DEEPSEEK_API_KEY=sk-your-key-here", _jsx("br", {}), "\u7136\u540E\u91CD\u542F APA Desktop \u5373\u53EF\u542F\u7528\u771F\u5B9E LLM \u51B3\u7B56\u3002"] })] }))] }))] }));
}
