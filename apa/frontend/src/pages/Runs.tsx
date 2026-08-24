import { useState } from "react";
import { Badge } from "../components/ui/primitives";
import { JobsPanel } from "../components/jobs/JobsPanel";
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
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, RunDetail>>({});

  async function toggleDetail(sid: string) {
    if (expanded === sid) { setExpanded(null); return; }
    setExpanded(sid);
    try {
      // POC：复用 sessions 数据展开（完整 journal 查询为 M2 增强）
      const recs = await api<Record<string, unknown>[]>(
        `/api/journal/records?session=${sid}`);
      setDetails(prev => ({ ...prev, [sid]: { session: sid, records: recs } }));
    } catch {
      setDetails(prev => ({ ...prev, [sid]: {
        session: sid, records: [{ info: "详细轨迹查询为 M2 增强" }] } }));
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
                      <span className="text-slate-300">{String(rec.kind)}</span>
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
    </div>
  );
}