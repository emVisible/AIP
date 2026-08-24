import { useQueryClient } from "@tanstack/react-query";
import { Activity, CircleCheck, Clock, Hand } from "lucide-react";

import { Badge } from "../components/ui/primitives";
import {
  useAnalytics,
  useSessions,
} from "../hooks/useSessions";
import { useJournalStream } from "../hooks/useJournalStream";
import type { JournalRecord } from "../api/types";
import { stateTone } from "../lib/utils";
import { cn } from "../lib/utils";

function StatCard({ icon: Icon, label, value }: {
  icon: typeof Activity; label: string; value: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200
                    bg-surface px-4 py-3 shadow-sm">
      <Icon size={20} className="text-brand" />
      <div>
        <p className="text-xs text-slate-400">{label}</p>
        <p className="text-lg font-semibold leading-tight">{value}</p>
      </div>
    </div>
  );
}

export function Dashboard() {
  const qc = useQueryClient();
  const sessions = useSessions();
  const analytics = useAnalytics();

  // SSE 实时流：journal 增量 → 失效 Query 触发刷新（单一职责：hook 只管流）
  const feed: JournalRecord[] = [];
  useJournalStream((record) => {
    qc.invalidateQueries({ queryKey: ["sessions"] });
    qc.invalidateQueries({ queryKey: ["analytics"] });
    feed.unshift(record);
    if (feed.length > 60) feed.pop();
  });

  const a = analytics.data;
  const rate = a?.actions.success_rate;
  const list = Object.values(sessions.data ?? {}).sort(
    (x, y) => y.last_ts - x.last_ts);

  return (
    <div className="space-y-5 max-w-6xl">
      <h1 className="text-xl font-bold">监控总览</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <StatCard icon={Activity} label="会话总数"
          value={String(a?.sessions.total ?? "—")} />
        <StatCard icon={CircleCheck} label="动作成功率"
          value={rate != null ? `${(rate * 100).toFixed(0)}%` : "—"} />
        <StatCard icon={Clock} label="耗时 p50"
          value={a?.actions.duration_ms.p50 != null
            ? `${a.actions.duration_ms.p50}ms` : "—"} />
        <StatCard icon={Hand} label="待审批任务"
          value={String(a?.human_tasks.open ?? 0)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 items-start">
        <div>
          <h2 className="text-sm font-semibold mb-2 text-slate-500">会话</h2>
          <div className="space-y-2">
            {list.map((s) => (
              <div key={s.id}
                className="flex items-center justify-between rounded-lg border
                           border-slate-200 bg-surface px-4 py-2.5">
                <div className="flex items-center gap-2.5 min-w-0">
                  <Badge tone={stateTone(s.state)}>{s.state}</Badge>
                  <span className="font-mono text-xs truncate">{s.id}</span>
                  {s.outcome && (
                    <span className={`text-xs ${s.outcome === "success"
                      ? "text-emerald-600" : "text-red-500"}`}>
                      → {s.outcome}
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-slate-300 shrink-0 ml-3">
                  {new Date(s.last_ts).toLocaleTimeString()}
                </span>
              </div>
            ))}
            {!list.length && (
              <p className="text-sm text-slate-400 py-8 text-center">
                暂无会话 —— 运行示例或等待调度器触发
              </p>
            )}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold mb-2 text-slate-500">实时事件流</h2>
          <div className={cn(
            "rounded-xl border border-slate-200 bg-surface divide-y divide-slate-50",
            "max-h-[420px] overflow-y-auto")}>
            {feed.length === 0 && (
              <p className="text-xs text-slate-400 p-3">（等待事件…）</p>
            )}
            {feed.map((r, i) => (
              <div key={i} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                <Badge tone={stateTone("")}>{r.kind}</Badge>
                <span className="font-mono truncate flex-1">
                  {r.name ?? r.status ?? r.to ?? r.task_id ?? ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
