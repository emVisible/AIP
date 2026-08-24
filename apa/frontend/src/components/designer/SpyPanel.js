import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { post } from "../../api/client";
/**
 * 桌面拾取面板（影刀 Ctrl 悬停体验）。
 * start → SSE hover 流（Electron overlay 高亮跟随）→ capture 存为步骤。
 * 纯浏览器环境（无 Electron）也能用：只是没有高亮框。
 */
export function SpyPanel({ onCapture }) {
    const [spying, setSpying] = useState(false);
    const [live, setLive] = useState(null);
    const [error, setError] = useState("");
    const esRef = useRef(null);
    const liveRef = useRef(null);
    liveRef.current = live;
    function cleanup() {
        esRef.current?.close();
        esRef.current = null;
        window.apaDesktop?.stopSpyOverlay?.();
    }
    useEffect(() => () => {
        if (esRef.current) {
            esRef.current.close();
            void post("/api/spy/stop", {});
        }
    }, []);
    async function start() {
        setError("");
        try {
            await post("/api/spy/start", {});
            setSpying(true);
            setLive(null);
            window.apaDesktop?.startSpyOverlay?.();
            const es = new EventSource("/api/spy/stream");
            esRef.current = es;
            es.onmessage = (ev) => {
                try {
                    const frame = JSON.parse(ev.data);
                    if (frame.type === "hover") {
                        setLive(frame.element ?? null);
                        const b = frame.element?.bounds;
                        if (b && b.w > 0) {
                            const el = frame.element;
                            window.apaDesktop?.spyBounds?.(b, `${el.app_name} · ${el.role}` +
                                (el.title ? ` · ${el.title.slice(0, 30)}` : ""));
                        }
                    }
                    else if (frame.type === "ended" || frame.type === "timeout") {
                        stop();
                    }
                }
                catch { /* 忽略坏帧 */ }
            };
            es.onerror = () => { };
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }
    function stop() {
        cleanup();
        setSpying(false);
        void post("/api/spy/stop", {});
    }
    async function capture() {
        try {
            const r = await post("/api/spy/capture", {});
            if (r.element)
                onCapture(r.element);
            else
                setError("光标下无可拾取元素");
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }
    return (_jsxs("div", { className: "mt-3 border rounded-lg p-2 bg-violet-50/40", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("p", { className: "text-xs font-semibold text-violet-700", children: "\u684C\u9762\u62FE\u53D6" }), _jsx("div", { className: "ml-auto flex gap-1", children: !spying ? (_jsx("button", { onClick: () => void start(), className: "px-2 py-0.5 text-xs font-medium text-white\n                         bg-violet-600 rounded hover:bg-violet-700", children: "\u5F00\u59CB" })) : (_jsxs(_Fragment, { children: [_jsx("button", { onClick: capture, className: "px-2 py-0.5 text-xs font-medium text-white\n                           bg-emerald-600 rounded hover:bg-emerald-700", children: "\u6355\u83B7" }), _jsx("button", { onClick: stop, className: "px-2 py-0.5 text-xs border rounded\n                           hover:bg-white", children: "\u505C\u6B62" })] })) })] }), spying && (_jsx("div", { className: "mt-1 text-[10px] leading-4 font-mono\n                        bg-white border border-violet-200 rounded p-1", children: live ? (_jsxs(_Fragment, { children: [_jsx("span", { className: "text-violet-600", children: live.app_name }), " · ", _jsx("span", { className: "font-semibold", children: live.role }), live.title ? ` · ${live.title.slice(0, 28)}` : "", live.bounds && (_jsxs("span", { className: "text-slate-400", children: [" ", "(", Math.round(live.bounds.x), ",", Math.round(live.bounds.y), " · ", Math.round(live.bounds.w), "\u00D7", Math.round(live.bounds.h), ")"] }))] })) : (_jsx("span", { className: "text-slate-400", children: "\u79FB\u52A8\u9F20\u6807\u5230\u76EE\u6807\u5143\u7D20\u2026" })) })), error && _jsx("p", { className: "mt-1 text-[10px] text-red-500", children: error })] }));
}
