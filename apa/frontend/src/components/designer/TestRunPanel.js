import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { api } from "../../api/client";
/** 沙盒试运行面板 —— 职责单一：输入事件+数据 → 展示步骤轨迹。 */
export function TestRunPanel({ yaml }) {
    const [ev, setEv] = useState("");
    const [data, setData] = useState("{}");
    const [result, setResult] = useState(null);
    const [running, setRunning] = useState(false);
    async function run() {
        setRunning(true);
        try {
            const d = await api("/api/processes/test", {
                method: "POST",
                body: JSON.stringify({ yaml, event: ev, data: JSON.parse(data || "{}") }),
            });
            setResult(d);
        }
        catch (e) {
            setResult({ outcome: "error", gateway_state: "", steps: [],
                error: String(e) });
        }
        finally {
            setRunning(false);
        }
    }
    return (_jsxs("div", { className: "space-y-2 p-1", children: [_jsx("p", { className: "text-[10px] font-semibold text-slate-400 uppercase", children: "\u6C99\u76D2\u8BD5\u8FD0\u884C\uFF08MockERP\uFF09" }), _jsx("input", { className: "w-full px-2 py-1 text-xs border rounded", placeholder: "\u89E6\u53D1\u4E8B\u4EF6\u540D", value: ev, onChange: (e) => setEv(e.target.value) }), _jsx("textarea", { className: "w-full px-2 py-1 text-xs font-mono border rounded resize-y", rows: 3, placeholder: "{}", value: data, onChange: (e) => setData(e.target.value) }), _jsx("button", { className: "w-full py-1.5 text-xs font-semibold text-white bg-brand\n                   rounded hover:bg-blue-700 disabled:opacity-50", disabled: running, onClick: run, children: running ? "运行中…" : "▶ 试运行" }), result != null && (_jsx("pre", { className: "text-[11px] bg-slate-900 text-green-300 p-2 rounded\n                        overflow-x-auto max-h-[240px]", children: JSON.stringify(result, null, 2) }))] }));
}
