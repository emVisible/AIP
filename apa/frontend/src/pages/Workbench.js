import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * 工作台（Phase B）—— 对话主轴 + 流程草稿审查。
 *
 * 单一职责：意图对话编排。编译结果经确认门写入设计器画布
 * （通过 zustand-less 约定：跳转 /designer?draft=<id>，草稿存
 * sessionStorage 由 DesignerPage 拾取）。
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Send } from "lucide-react";
export function Workbench() {
    const [msgs, setMsgs] = useState([{
            role: "apa",
            text: "描述你想自动化的任务，例如：" +
                "「每天9点抓竞品价格对比昨日，涨5%就通知我」",
        }]);
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const [pending, setPending] = useState(null);
    const nav = useNavigate();
    const listRef = useRef(null);
    useEffect(() => {
        listRef.current?.scrollTo({ top: 999999 });
    }, [msgs]);
    function push(m) { setMsgs(prev => [...prev, m]); }
    async function send() {
        const text = input.trim();
        if (!text || busy)
            return;
        push({ role: "user", text });
        setInput("");
        setBusy(true);
        try {
            const r = await fetch("/api/intent/compile", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ utterance: text }),
            });
            if (r.status === 501) {
                push({ role: "apa",
                    text: "当前服务未启用意图编译（需 serve + LLM 配置）。" +
                        "你可以直接在设计器手工搭建流程。" });
                return;
            }
            const d = await r.json();
            if (d.ok && d.process_yaml) {
                const draftId = `draft_${Date.now().toString(36)}`;
                sessionStorage.setItem(`apa_draft_${draftId}`, d.process_yaml);
                setPending({ yaml: d.process_yaml, tid: d.template_id ?? "" });
                push({ role: "apa", draftId,
                    text: `已按「${d.template_id}」模板起草流程。` +
                        "请在右侧/下方检查后确认，或继续补充信息修改。" });
            }
            else if (d.questions?.length) {
                push({ role: "apa",
                    text: "需要补充几个信息：\n" +
                        d.questions.map((q) => `· ${q}`).join("\n") });
            }
            else {
                push({ role: "apa",
                    text: d.error === "no_template_match"
                        ? "暂时没有匹配的场景模板。目前支持：价格监控、" +
                            "客服质检。更多场景持续接入中。"
                        : `编译失败：${d.error ?? "未知原因"}` });
            }
        }
        catch (e) {
            push({ role: "apa",
                text: `请求失败：${e instanceof Error ? e.message : e}` });
        }
        finally {
            setBusy(false);
        }
    }
    function confirmDraft() {
        if (!pending)
            return;
        sessionStorage.setItem("apa_draft_import", pending.yaml);
        nav("/designer");
    }
    return (_jsxs("div", { className: "h-full flex flex-col max-w-3xl mx-auto p-4 gap-3", children: [_jsxs("header", { className: "flex items-center justify-between", children: [_jsx("h1", { className: "text-lg font-bold tracking-tight", children: "\u5DE5\u4F5C\u53F0" }), _jsx("span", { className: "text-[10px] text-slate-400", children: "\u63CF\u8FF0\u4EFB\u52A1 \u2192 APA \u8D77\u8349\u6D41\u7A0B \u2192 \u4F60\u786E\u8BA4\u540E\u6267\u884C" })] }), _jsxs("div", { ref: listRef, className: "flex-1 overflow-y-auto space-y-2 pr-1", children: [msgs.map((m, i) => (_jsx("div", { className: m.role === "user" ? "flex justify-end" : "", children: _jsx("div", { className: `max-w-[85%] rounded-xl px-3 py-2 text-xs
                whitespace-pre-wrap leading-relaxed ${m.role === "user"
                                ? "bg-zinc-900 text-white rounded-br-sm"
                                : "bg-white border border-slate-200 rounded-bl-sm "
                                    + "text-slate-700 shadow-sm"}`, children: m.text }) }, i))), pending && (_jsxs("div", { className: "bg-emerald-50 border border-emerald-200\n                          rounded-xl px-3 py-2.5 text-xs space-y-2", children: [_jsxs("p", { className: "font-medium text-emerald-700", children: ["\u8349\u7A3F\u5C31\u7EEA \u00B7 \u6A21\u677F ", pending.tid] }), _jsx("pre", { className: "text-[10px] font-mono bg-white rounded\n                            border border-emerald-100 p-2 max-h-40\n                            overflow-auto whitespace-pre-wrap", children: pending.yaml }), _jsxs("div", { className: "flex gap-2", children: [_jsx("button", { onClick: confirmDraft, className: "px-3 py-1 rounded-md bg-zinc-900 text-white\n                           text-xs font-medium hover:bg-zinc-700", children: "\u5BFC\u5165\u8BBE\u8BA1\u5668" }), _jsx("button", { onClick: () => setPending(null), className: "px-3 py-1 rounded-md border border-slate-200\n                           text-xs hover:bg-white", children: "\u4E22\u5F03" })] })] }))] }), _jsxs("form", { className: "flex gap-2", onSubmit: (e) => { e.preventDefault(); void send(); }, children: [_jsx("input", { autoFocus: true, value: input, onChange: (e) => setInput(e.target.value), placeholder: "\u7528\u4E00\u53E5\u8BDD\u63CF\u8FF0\u81EA\u52A8\u5316\u4EFB\u52A1\u2026", className: "flex-1 h-9 px-3 text-xs border border-slate-200\n                     rounded-md focus:border-slate-400 outline-none\n                     focus:ring-2 ring-blue-500/20" }), _jsx("button", { type: "submit", disabled: busy || !input.trim(), className: "h-9 w-9 inline-flex items-center justify-center\n                     rounded-md bg-zinc-900 text-white\n                     disabled:opacity-40 hover:bg-zinc-700", children: _jsx(Send, { size: 14 }) })] })] }));
}
