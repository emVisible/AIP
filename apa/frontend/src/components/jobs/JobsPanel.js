import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
/**
 * 定时任务管理（影刀「计划任务」对标）。
 * 列表 + cron 编辑弹窗 + 立即运行；变更即持久化 scheduler.yaml 并热生效。
 */
import { useCallback, useEffect, useState } from "react";
import { Clock, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { Badge, Button, Card, Dialog, Field, IconButton, Input, Select } from "../ui";
export function JobsPanel() {
    const [jobs, setJobs] = useState([]);
    const [loaded, setLoaded] = useState(false);
    const [editing, setEditing] = useState(null);
    const [msg, setMsg] = useState("");
    const refresh = useCallback(async () => {
        try {
            const r = await fetch("/api/jobs").then(x => x.json());
            setJobs(r.jobs ?? []);
            setLoaded(true);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }, []);
    useEffect(() => { void refresh(); }, [refresh]);
    async function save(spec) {
        if (!spec)
            return;
        const body = {
            id: spec.id.trim(), kind: spec.kind, process: spec.process.trim(),
            expr: spec.kind === "cron" ? spec.expr.trim() : undefined,
            event: spec.kind === "event" ? spec.event.trim() : undefined,
        };
        try {
            const r = await fetch("/api/jobs/save", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!r.ok)
                throw new Error(await r.text());
            setEditing(null);
            setMsg(`已保存 ${body.id} ✓`);
            await refresh();
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    async function remove(id) {
        try {
            await fetch(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
            setMsg(`已删除 ${id}`);
            await refresh();
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    async function runNow(id) {
        try {
            await fetch(`/api/jobs/${encodeURIComponent(id)}/run`, { method: "POST" });
            setMsg(`${id} 已触发，结果见运行历史`);
        }
        catch (e) {
            setMsg(e instanceof Error ? e.message : String(e));
        }
    }
    return (_jsxs(Card, { children: [_jsxs("div", { className: "flex items-center justify-between px-3 py-2\n                      border-b border-slate-100", children: [_jsxs("span", { className: "flex items-center gap-1.5 text-xs font-semibold\n                         text-slate-700", children: [_jsx(Clock, { size: 13 }), " \u5B9A\u65F6\u4EFB\u52A1 (", jobs.length, ")"] }), _jsxs(Button, { size: "sm", variant: "secondary", onClick: () => setEditing({ id: "", kind: "cron", process: "",
                            expr: "0 * * * *", event: "" }), children: [_jsx(Plus, { size: 13 }), " \u65B0\u5EFA"] })] }), _jsxs("div", { className: "divide-y divide-slate-50", children: [jobs.map(j => (_jsxs("div", { className: "flex items-center gap-2 px-3 py-2\n                                     hover:bg-slate-50/60", children: [_jsx(Badge, { tone: j.kind === "cron" ? "blue" : "violet", children: j.kind }), _jsx("span", { className: "font-mono text-xs text-slate-700", children: j.id }), _jsx("span", { className: "font-mono text-[10px] text-slate-400 truncate", children: j.kind === "cron" ? j.expr : j.event }), !j.exists && _jsx(Badge, { tone: "red", children: "\u6D41\u7A0B\u7F3A\u5931" }), _jsxs("span", { className: "ml-auto text-[10px] text-slate-400", children: [j.next_run ? `下次 ${j.next_run}` : "", j.next_error ? "cron 无效" : ""] }), _jsx(IconButton, { label: "\u7ACB\u5373\u8FD0\u884C", onClick: () => void runNow(j.id), children: _jsx(Play, { size: 12 }) }), _jsx(IconButton, { label: "\u7F16\u8F91", onClick: () => setEditing({
                                    id: j.id, kind: j.kind, process: j.process,
                                    expr: j.expr ?? "0 * * * *", event: j.event ?? ""
                                }), children: _jsx(Pencil, { size: 12 }) }), _jsx(IconButton, { label: "\u5220\u9664", className: "hover:text-red-600", onClick: () => void remove(j.id), children: _jsx(Trash2, { size: 12 }) })] }, j.id))), loaded && !jobs.length && (_jsx("p", { className: "px-3 py-4 text-xs text-slate-400", children: "\u6682\u65E0\u4EFB\u52A1\u2014\u2014\u65B0\u5EFA\u4E00\u4E2A cron \u6216\u4E8B\u4EF6\u89E6\u53D1\u4EFB\u52A1" })), !loaded && (_jsx("p", { className: "px-3 py-4 text-xs text-slate-400", children: "\u52A0\u8F7D\u4E2D\u2026" }))] }), _jsx(Dialog, { open: !!editing, onClose: () => setEditing(null), width: 480, children: editing && (_jsxs(_Fragment, { children: [_jsx("div", { className: "px-4 py-3 border-b border-slate-100", children: _jsx("h2", { className: "text-sm font-semibold text-slate-800", children: editing.id ? `编辑任务 ${editing.id}` : "新建任务" }) }), _jsxs("div", { className: "px-4 py-3 space-y-3 max-h-[60vh] overflow-y-auto", children: [_jsx(Field, { label: "\u4EFB\u52A1 ID", children: _jsx(Input, { value: editing.id, disabled: !!jobs.find(j => j.id === editing.id), onChange: e => setEditing({ ...editing,
                                            id: e.target.value }) }) }), _jsx(Field, { label: "\u89E6\u53D1\u65B9\u5F0F", children: _jsxs(Select, { value: editing.kind, onChange: e => setEditing({ ...editing,
                                            kind: e.target.value }), children: [_jsx("option", { value: "cron", children: "\u5B9A\u65F6 (cron)" }), _jsx("option", { value: "event", children: "\u4E8B\u4EF6" })] }) }), editing.kind === "cron" ? (_jsx(Field, { label: "Cron \u8868\u8FBE\u5F0F", hint: "\u5206 \u65F6 \u65E5 \u6708 \u5468", children: _jsx(Input, { value: editing.expr, className: "font-mono", placeholder: "0 9 * * *", onChange: e => setEditing({ ...editing,
                                            expr: e.target.value }) }) })) : (_jsx(Field, { label: "\u4E8B\u4EF6\u540D", hint: "\u4E09\u6BB5\u5F0F a.b.c", children: _jsx(Input, { value: editing.event, className: "font-mono", placeholder: "erp.order.created", onChange: e => setEditing({ ...editing,
                                            event: e.target.value }) }) })), _jsx(Field, { label: "\u6D41\u7A0B ID", children: _jsx(Input, { value: editing.process, className: "font-mono", placeholder: "process \u6587\u4EF6\u540D", onChange: e => setEditing({ ...editing,
                                            process: e.target.value }) }) })] }), _jsxs("div", { className: "flex justify-end gap-2 px-4 py-2.5 border-t\n                            border-slate-100 bg-slate-50/50", children: [_jsx(Button, { size: "sm", variant: "ghost", onClick: () => setEditing(null), children: "\u53D6\u6D88" }), _jsx(Button, { size: "sm", variant: "primary", onClick: () => void save(editing), children: "\u4FDD\u5B58" })] })] })) }), msg && _jsx("p", { className: "px-3 py-1.5 text-[10px] text-slate-500", children: msg })] }));
}
