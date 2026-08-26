/**
 * 工作台（Phase B + H1 会话层）—— 对话主轴 + 流程草稿审查。
 *
 * H1 融合（docs/harness-fusion.md §4.1）：对话持久化到会话事件溯源层，
 * 「模型可见 ⟺ 已记录」——每条消息/草稿/决策先落事件再渲染。
 * 刷新页面经投影完整恢复；草稿审批状态机持久化。
 *
 * 编译结果经确认门写入设计器画布（sessionStorage 约定：
 * apa_draft_import → /designer 拾取）。
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Send } from "lucide-react";

import { studioRpc } from "../api/studio";

interface DraftInfo {
  id: string;
  yaml: string;
  tid: string;
  state: "pending" | "approved" | "discarded";
}

interface Msg {
  role: "user" | "apa";
  text: string;
  draft?: DraftInfo;
}

/** 投影视图条目 → 消息流（sessions.project_events 的 TS 镜像）。 */
function viewToMsgs(view: any[]): Msg[] {
  const out: Msg[] = [];
  for (const it of view ?? []) {
    if (it.type === "message") {
      out.push({ role: it.role === "user" ? "user" : "apa",
                 text: String(it.text ?? "") });
    } else if (it.type === "draft") {
      out.push({ role: "apa", text: "", draft: {
        id: String(it.id), yaml: String(it.yaml ?? ""),
        tid: String(it.template ?? ""),
        state: (it.state as DraftInfo["state"]) ?? "pending",
      }});
    }
  }
  return out;
}

const SESSION_KEY = "apa_session_id";

export function Workbench() {
  const sidRef = useRef<string>(
    localStorage.getItem(SESSION_KEY) || "workbench");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem(SESSION_KEY, sidRef.current);
    // H3：经 Studio RPC 通道读取投影（类型单源 studioProtocol.ts）
    studioRpc<{ id: string; view: any[] }>("session.read",
                                           { sid: sidRef.current })
      .then((d) => setMsgs(viewToMsgs(d.view)))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 999999 });
  }, [msgs]);

  /** 先落事件，再更新本地视图——不变量的前端半边。 */
  async function logEvent(kind: string, payload: Record<string, unknown>) {
    try {
      await studioRpc("session.append",
                      { sid: sidRef.current, kind, payload });
    } catch { /* 后端不可达时本地仍可用（降级） */ }
  }

  function push(m: Msg) {
    setMsgs(prev => [...prev, m]);
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    push({ role: "user", text });
    setInput("");
    await logEvent("message.user", { text });
    setBusy(true);

    try {
      const r = await fetch("/api/intent/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ utterance: text }),
      });

      let reply = "";
      if (r.status === 501) {
        reply = "当前服务未启用意图编译（需 serve + LLM 配置）。" +
                "你可以直接在设计器手工搭建流程。";
      } else {
        const d = await r.json();
        if (d.ok && d.process_yaml) {
          const draftId = `draft_${Date.now().toString(36)}`;
          await logEvent("draft.created", {
            id: draftId, yaml: d.process_yaml,
            template: d.template_id ?? "",
          });
          push({ role: "apa", text: "",
            draft: { id: draftId, yaml: d.process_yaml,
                     tid: d.template_id ?? "", state: "pending" } });
          reply = "";
        } else if (d.questions?.length) {
          reply = "需要补充几个信息：\n" +
                  d.questions.map((q: string) => `· ${q}`).join("\n");
        } else {
          reply = d.error === "no_template_match"
            ? "暂时没有匹配的场景模板。目前支持：价格监控、" +
              "客服质检。更多场景持续接入中。"
            : `编译失败：${d.error ?? "未知原因"}`;
        }
      }
      if (reply) {
        push({ role: "apa", text: reply });
        await logEvent("message.assistant", { text: reply });
      }
    } catch (e) {
      const msg = `请求失败：${e instanceof Error ? e.message : e}`;
      push({ role: "apa", text: msg });
      await logEvent("message.assistant", { text: msg });
    } finally {
      setBusy(false);
    }
  }

  async function confirmDraft(d: DraftInfo) {
    await logEvent("draft.approved", { id: d.id });
    setMsgs(prev => prev.map(m =>
      m.draft?.id === d.id
        ? { ...m, draft: { ...m.draft!, state: "approved" } } : m));
    sessionStorage.setItem("apa_draft_import", d.yaml);
    // H2 溯源凭证：设计器侧保存/试运行必须携带，服务端校验批准事件
    sessionStorage.setItem("apa_draft_source", JSON.stringify({
      session_id: sidRef.current, draft_id: d.id,
    }));
    nav("/designer");
  }

  async function discardDraft(d: DraftInfo) {
    await logEvent("draft.discarded", { id: d.id });
    setMsgs(prev => prev.map(m =>
      m.draft?.id === d.id
        ? { ...m, draft: { ...m.draft!, state: "discarded" } } : m));
  }

  function renderDraft(d: DraftInfo) {
    return (
      <div className={`rounded-xl px-3 py-2.5 text-xs space-y-2 border ${
        d.state === "discarded"
          ? "bg-slate-50 border-slate-200 opacity-60"
          : d.state === "approved"
            ? "bg-emerald-50 border-emerald-200"
            : "bg-white border-slate-200 shadow-sm"}`}>
        <p className="font-medium flex items-center gap-2">
          {d.state === "approved" ? (
            <span className="text-emerald-600">✓ 已批准并导入设计器</span>
          ) : d.state === "discarded" ? (
            <span className="text-slate-400">已丢弃的草稿 · {d.tid}</span>
          ) : (
            <span className="text-emerald-700">草稿就绪 · 模板 {d.tid}</span>
          )}
        </p>
        <pre className="text-[10px] font-mono bg-white rounded
                        border border-slate-100 p-2 max-h-40
                        overflow-auto whitespace-pre-wrap">
          {d.yaml}
        </pre>
        {d.state === "pending" && (
          <div className="flex gap-2">
            <button onClick={() => void confirmDraft(d)}
              className="px-3 py-1 rounded-md bg-zinc-900 text-white
                         text-xs font-medium hover:bg-zinc-700">
              导入设计器
            </button>
            <button onClick={() => void discardDraft(d)}
              className="px-3 py-1 rounded-md border border-slate-200
                         text-xs hover:bg-slate-50">
              丢弃
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col max-w-3xl mx-auto p-4 gap-3">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-bold tracking-tight">工作台</h1>
        <span className="text-[10px] text-slate-400">
          描述任务 → APA 起草流程 → 你确认后执行 · 会话已持久化
        </span>
      </header>

      {/* 对话流 */}
      <div ref={listRef}
           className="flex-1 overflow-y-auto space-y-2 pr-1">
        {loaded && !msgs.length && (
          <div className="h-full flex items-center justify-center">
            <p className="text-xs text-slate-300">
              描述你想自动化的任务，例如：「每天9点抓竞品价格对比昨日，
              涨5%就通知我」
            </p>
          </div>
        )}
        {msgs.map((m, i) => (
          m.draft ? (
            <div key={i}>{renderDraft(m.draft)}</div>
          ) : (
            <div key={i} className={m.role === "user"
              ? "flex justify-end" : ""}>
              <div className={`max-w-[85%] rounded-xl px-3 py-2 text-xs
                  whitespace-pre-wrap leading-relaxed ${
                m.role === "user"
                  ? "bg-zinc-900 text-white rounded-br-sm"
                  : "bg-white border border-slate-200 rounded-bl-sm "
                    + "text-slate-700 shadow-sm"}`}>
                {m.text}
              </div>
            </div>
          )
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-xl
                            px-3 py-2 text-xs text-slate-400">
              APA 正在思考…
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
