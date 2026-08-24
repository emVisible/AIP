import { useState } from "react";
import { Badge } from "../components/ui/primitives";
import { JobsPanel } from "../components/jobs/JobsPanel";
import { Dialog, Button as UiButton } from "../components/ui";
import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";
import { stateTone } from "../lib/utils";

interface RunDetail {
  session: string;
  records: Record<string, unknown>[];
}

export function Runs() {
  const sessions = useSessions();
  const [tab, setTab] = useState<"runs" | "jobs">("runs");
  const [diag, setDiag] = useState<null | {
    session: string; loading: boolean;
    explanation?: string; suggestion?: string; error?: string;
  }>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, RunDetail>>({});


  async function diagnoseSession(sid: string) {
    setDiag({ session: sid, loading: true });
    try {
      const r = await fetch("/api/intent/explain-failure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: sid }),
      });
      const d = await r.json();
      setDiag({ session: sid, loading: false,
                explanation: d.explanation,
                suggestion: d.suggestion,
                error: d.detail ?? d.error });
    } catch (e) {
      setDiag({ session: sid, loading: false,
                error: e instanceof Error ? e.message : String(e) });
    }
  }

  async function toggleDetail(sid: string) {
    if (expanded === sid) { setExpanded(null); return; }
    setExpanded(sid);
    try {
      const d = await api<{ records: Record<string, unknown>[] }>(
        `/api/journal/records?session=${encodeURIComponent(sid)}`);
      setDetails(prev => ({ ...prev,
        [sid]: { session: sid, records: d.records ?? [] } }));
    } catch (e) {
      setDetails(prev => ({ ...prev, [sid]: {
        session: sid,
        records: [{ info: e instanceof Error ? e.message : String(e) }] } }));
    }
  }

  const list = Object.values(sessions.data ?? {})
    .sort((a, b) => b.last_ts - a.last_ts);

  return (
    <div className="space-y-4 max-w-6xl">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold">运行中心</h1>
        <nav className="ml-2 flex items-center gap-1">
          {([["runs", "运行历史"], ["jobs", "定时任务"]] as const).map(
            ([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`h-7 px-3 rounded-md text-xs font-medium
                            transition-colors ${tab === k
                  ? "bg-zinc-900 text-white"
                  : "text-slate-500 hover:bg-slate-100"}`}>
                {label}
              </button>
            ))}
        </nav>
      </div>

      {tab === "jobs" && <JobsPanel />}

      {tab === "runs" && (
      <>

      {!list.length && (
        <p className="text-sm text-slate-400 py-8 text-center">
          暂无运行记录</p>
      )}

      <div className="space-y-3">
        {list.map(s => (
          <div key={s.id}
            className="rounded-xl border border-slate-200 bg-surface shadow-sm
                       overflow-hidden">
            {/* 会话摘要行 */}
            <div
              className="flex items-center justify-between px-4 py-3 cursor-pointer
                         hover:bg-slate-50 transition-colors"
              onClick={() => void toggleDetail(s.id)}
            >
              <div className="flex items-center gap-3">
                <Badge tone={stateTone(s.state)}>{s.state}</Badge>
                <span className="font-mono text-sm">{s.id}</span>
                {(s.state === "FAILED" || s.outcome === "failed") && (
                  <button
                    onClick={(e) => { e.stopPropagation();
                                      void diagnoseSession(s.id); }}
                    className="text-[10px] px-1.5 py-0.5 rounded
                               border border-violet-200 text-violet-600
                               hover:bg-violet-50">
                    APA 诊断
                  </button>
                )}
                {s.outcome && (
                  <span className="text-xs text-slate-400">→ {s.outcome}</span>
                )}
              </div>
              <div className="flex items-center gap-4 text-xs text-slate-400">
                <span>
                  游标: {Object.entries(s.cursors)
                    .map(([k, v]) => `${k}:${v}`).join(" ") || "—"}
                </span>
                {s.tenant && <span className="rounded bg-slate-100 px-1.5">
                  {s.tenant}</span>}
              </div>
            </div>

            {/* 展开详情 */}
            {expanded === s.id && details[s.id] && (
              <div className="border-t border-slate-100 px-4 py-3 bg-slate-50">
                <p className="text-[10px] text-slate-400 uppercase mb-1">
                  Journal Records</p>
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                  {(details[s.id]?.records ?? []).map((rec, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs
                                            font-mono text-slate-600">
                      <span className="text-slate-300">{String(rec.kind ?? rec.info ?? "")}</span>
                      {rec.to ? <Badge tone={stateTone(String(rec.to))}>{String(rec.to)}</Badge> : null}
                      {rec.outcome ? (
                        <span className={String(rec.outcome) === "success"
                          ? "text-emerald-600" : "text-red-500"}>
                          {String(rec.outcome)}
                        </span>) : null}
                      {rec.step ? <span>{String(rec.step)}</span> : null}
                      {rec.action ? <span className="text-slate-400">{String(rec.action)}</span> : null}
                      <span>{String(rec.to ?? rec.status ??
                             rec.name ?? "")}</span>
                    </div>
                  ))}
                  {!(details[s.id]?.records ?? []).length && (
                    <p className="text-xs text-slate-400">（无记录）</p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      </>
      )}

      {/* 失败诊断弹窗 */}
      <Dialog open={!!diag} onClose={() => setDiag(null)} width={520}>
        {diag && (
          <>
            <div className="px-4 py-3 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-800">
                APA 失败诊断
                <span className="ml-2 font-mono text-[10px]
                                 text-slate-400">{diag.session}</span>
              </h2>
            </div>
            <div className="px-4 py-3 space-y-3 text-xs max-h-[50vh]
                            overflow-y-auto">
              {diag.loading && (
                <p className="text-slate-400">分析中…</p>
              )}
              {!diag.loading && diag.error && (
                <p className="text-red-500">{diag.error}</p>
              )}
              {!diag.loading && diag.explanation && (
                <div className="space-y-1">
                  <p className="font-medium text-slate-600">根因</p>
                  <p className="text-slate-700">{diag.explanation}</p>
                </div>
              )}
              {!diag.loading && diag.suggestion && (
                <div className="space-y-1">
                  <p className="font-medium text-slate-600">修正建议</p>
                  <p className="text-slate-700">{diag.suggestion}</p>
                </div>
              )}
            </div>
            <div className="flex justify-end px-4 py-2.5 border-t
                            border-slate-100 bg-slate-50/50">
              <UiButton size="sm" variant="ghost"
                        onClick={() => setDiag(null)}>关闭</UiButton>
            </div>
          </>
        )}
      </Dialog>
    </div>
  );
}