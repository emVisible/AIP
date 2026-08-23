import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { post } from "../../api/client";
/**
 * 数据抓取向导面板（影刀数据抓取同款交互）。
 * 输入 URL → 浏览器点两行 → 自动推断行选择器 → 点单元格加列
 * → 预览 → 一键生成 extract_table(+foreach) 步骤入画布。
 */
export function ScrapePanel({ onGenerate }) {
    const [url, setUrl] = useState("https://");
    const [sid, setSid] = useState("");
    const [st, setSt] = useState(null);
    const [colName, setColName] = useState("");
    const [preview, setPreview] = useState(null);
    const [msg, setMsg] = useState("");
    const pollRef = useRef(null);
    useEffect(() => () => {
        if (pollRef.current)
            window.clearInterval(pollRef.current);
        if (sid)
            void post(`/api/scrape/${sid}/stop`, {});
    }, [sid]);
    async function start() {
        setMsg("");
        setPreview(null);
        try {
            const r = await post("/api/scrape/start", { url });
            setSid(r.session_id);
            setMsg("向导浏览器已打开：依次点击【第1行】【第2行】");
            pollRef.current = window.setInterval(async () => {
                try {
                    const s = await fetch(`/api/scrape/status/${r.session_id}`)
                        .then(x => x.json());
                    setSt(s);
                    if (!s.active)
                        stop();
                }
                catch { /* ignore */ }
            }, 600);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    function stop() {
        if (pollRef.current)
            window.clearInterval(pollRef.current);
        if (sid)
            void post(`/api/scrape/${sid}/stop`, {});
        setSid("");
        setSt(null);
    }
    async function assign(role) {
        if (!sid)
            return;
        try {
            const r = await post(`/api/scrape/${sid}/assign`, { role, name: colName });
            if (role === "row" && st && st.rows_marked >= 2) {
                setMsg(`行选择器已推断 ✓`);
            }
            else if (r.assigned === "column") {
                setColName("");
            }
            // 立即刷新状态
            const s = await fetch(`/api/scrape/status/${sid}`).then(x => x.json());
            setSt(s);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    async function doPreview() {
        if (!sid)
            return;
        try {
            const r = await post(`/api/scrape/${sid}/preview`, { max_rows: 5 });
            setPreview(r.rows);
            setMsg(`预览 ${r.count} 行 ✓`);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    async function generate() {
        if (!sid)
            return;
        const base = `scrape_${Date.now().toString(36).slice(-4)}`;
        try {
            const r = await post(`/api/scrape/${sid}/generate`, { base_id: base, with_loop: false });
            onGenerate(r.steps, `${base}（${r.step_count} 步骤）`);
            setMsg(`已生成 ${r.step_count} 个步骤入画布 ✓`);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    return (_jsxs("div", { className: "mt-3 border rounded-lg p-2 bg-sky-50/40", children: [_jsx("p", { className: "text-xs font-semibold text-sky-700", children: "\uD83D\uDCCA \u6570\u636E\u6293\u53D6\u5411\u5BFC" }), !sid ? (_jsxs("div", { className: "mt-1 flex gap-1", children: [_jsx("input", { value: url, onChange: e => setUrl(e.target.value), placeholder: "https://\u2026", className: "flex-1 min-w-0 px-2 py-1 text-xs border rounded" }), _jsx("button", { onClick: () => void start(), className: "px-2 py-1 text-xs font-medium text-white bg-sky-600\n                       rounded hover:bg-sky-700", children: "\u5F00\u59CB" })] })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "mt-1 text-[10px] font-mono bg-white border\n                          border-sky-200 rounded p-1 leading-4", children: [_jsxs("div", { children: ["\u884C\u6807\u8BB0: ", _jsx("b", { children: st?.rows_marked ?? 0 }), "/2", st?.row_selector && (_jsxs(_Fragment, { children: [" \u00B7 \u9009\u62E9\u5668:", _jsx("span", { className: "text-sky-700", children: st.row_selector }), _jsxs("span", { className: "text-slate-400", children: [" (", st.strategy, ")"] })] }))] }), Object.keys(st?.columns ?? {}).length > 0 && (_jsxs("div", { children: ["\u5217: ", Object.entries(st.columns).map(([k, v]) => (_jsxs("span", { className: "mr-1", children: [_jsx("b", { children: k }), "=", v] }, k)))] }))] }), _jsx("div", { className: "mt-1 flex gap-1 flex-wrap", children: (st?.rows_marked ?? 0) < 2 ? (_jsxs("span", { className: "text-[10px] text-slate-500 py-1", children: ["\u8BF7\u5728\u6253\u5F00\u7684\u6D4F\u89C8\u5668\u4E2D\u70B9\u51FB\u7B2C", (st?.rows_marked ?? 0) + 1, "\u884C\u2026"] })) : (_jsxs(_Fragment, { children: [_jsx("input", { value: colName, onChange: e => setColName(e.target.value), placeholder: "\u5217\u540D", className: "w-16 px-1 py-0.5 text-xs border rounded" }), _jsx("button", { onClick: () => void assign("column"), disabled: !colName, className: "px-2 py-0.5 text-xs border rounded disabled:opacity-40\n                             hover:bg-white", children: "+\u6DFB\u52A0\u5217" }), _jsx("button", { onClick: () => void doPreview(), className: "px-2 py-0.5 text-xs border rounded hover:bg-white", children: "\u9884\u89C8" }), _jsx("button", { onClick: () => void generate(), className: "ml-auto px-2 py-0.5 text-xs font-medium text-white\n                             bg-emerald-600 rounded hover:bg-emerald-700", children: "\u751F\u6210\u6B65\u9AA4" }), _jsx("button", { onClick: stop, className: "px-2 py-0.5 text-xs border rounded hover:bg-white", children: "\u5173\u95ED" })] })) }), preview && preview.length > 0 && (() => {
                        const first = preview[0] ?? {};
                        return (_jsxs("table", { className: "mt-1 w-full text-[10px] font-mono border\n                              border-slate-200 bg-white", children: [_jsx("thead", { children: _jsx("tr", { className: "bg-slate-50", children: Object.keys(first).map(k => (_jsx("th", { className: "border-b px-1 text-left", children: k }, k))) }) }), _jsx("tbody", { children: preview.map((row, i) => (_jsx("tr", { children: Object.values(row).map((v, j) => (_jsx("td", { className: "border-t px-1 truncate max-w-[90px]", children: v }, j))) }, i))) })] }));
                    })()] })), msg && _jsx("p", { className: "mt-1 text-[10px] text-slate-500", children: msg })] }));
}
