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

interface Msg {
  role: "user" | "apa";
  text: string;
  questions?: string[];
  draftId?: string;
}

/** 模块级持久化（跨路由导航不丢；页面刷新重置）。 */
let _msgCache: Msg[] | null = null;
let _pendingCache: { yaml: string; tid: string } | null = null;

export function Workbench() {
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    if (_msgCache) return _msgCache;
    return [{ role: "apa",
      text: "描述你想自动化的任务，例如：" +
            "「每天9点抓竞品价格对比昨日，涨5%就通知我」" }];
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ yaml: string; tid: string }
                                       | null>(_pendingCache);
  const nav = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 999999 });
  }, [msgs]);

  function push(m: Msg) {
    setMsgs(prev => {
      _msgCache = [...prev, m];
      return _msgCache;
    });
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
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
        _pendingCache = { yaml: d.process_yaml, tid: d.template_id ?? "" };
        setPending(_pendingCache);
        push({ role: "apa", draftId,
               text: `已按「${d.template_id}」模板起草流程。` +
                     "请在右侧/下方检查后确认，或继续补充信息修改。" });
      } else if (d.questions?.length) {
        push({ role: "apa",
               text: "需要补充几个信息：\n" +
                     d.questions.map((q: string) => `· ${q}`).join("\n") });
      } else {
        push({ role: "apa",
               text: d.error === "no_template_match"
                 ? "暂时没有匹配的场景模板。目前支持：价格监控、" +
                   "客服质检。更多场景持续接入中。"
                 : `编译失败：${d.error ?? "未知原因"}` });
      }
    } catch (e) {
      push({ role: "apa",
             text: `请求失败：${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  function confirmDraft() {
    if (!pending) return;
    sessionStorage.setItem("apa_draft_import", pending.yaml);
    nav("/designer");
  }

  return (
    <div className="h-full flex flex-col max-w-3xl mx-auto p-4 gap-3">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-bold tracking-tight">工作台</h1>
        <span className="text-[10px] text-slate-400">
          描述任务 → APA 起草流程 → 你确认后执行
        </span>
      </header>

      {/* 对话流 */}
      <div ref={listRef}
           className="flex-1 overflow-y-auto space-y-2 pr-1">
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs
                whitespace-pre-wrap leading-relaxed ${
              m.role === "user"
                ? "bg-zinc-900 text-white rounded-br-sm"
                : "bg-white border border-slate-200 rounded-bl-sm "
                  + "text-slate-700 shadow-sm"}`}>
              {m.text}
            </div>
          </div>
        ))}

        {pending && (
          <div className="bg-emerald-50 border border-emerald-200
                          rounded-xl px-3 py-2.5 text-xs space-y-2">
            <p className="font-medium text-emerald-700">
              草稿就绪 · 模板 {pending.tid}
            </p>
            <pre className="text-[10px] font-mono bg-white rounded
                            border border-emerald-100 p-2 max-h-40
                            overflow-auto whitespace-pre-wrap">
              {pending.yaml}
            </pre>
            <div className="flex gap-2">
              <button onClick={confirmDraft}
                className="px-3 py-1 rounded-md bg-zinc-900 text-white
                           text-xs font-medium hover:bg-zinc-700">
                导入设计器
              </button>
              <button onClick={() => { _pendingCache = null; setPending(null); }}
                className="px-3 py-1 rounded-md border border-slate-200
                           text-xs hover:bg-white">
                丢弃
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <form className="flex gap-2"
            onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <input autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="用一句话描述自动化任务…"
          className="flex-1 h-9 px-3 text-xs border border-slate-200
                     rounded-md focus:border-slate-400 outline-none
                     focus:ring-2 ring-blue-500/20" />
        <button type="submit" disabled={busy || !input.trim()}
          className="h-9 w-9 inline-flex items-center justify-center
                     rounded-md bg-zinc-900 text-white
                     disabled:opacity-40 hover:bg-zinc-700">
          <Send size={14} />
        </button>
      </form>
    </div>
  );
}