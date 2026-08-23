import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";

export function Hitl() {
  const qc = useQueryClient();
  const sessions = useSessions();
  const [resolving, setResolving] = useState<string | null>(null);

  const openTasks = Object.values(sessions.data ?? {}).flatMap(s =>
    s.tasks_open.map(t => ({ ...t, session: s.id })));

  async function resolve(taskId: string, outcome: string) {
    setResolving(taskId);
    try {
      await api(`/tasks/${taskId}/resolve`, {
        method: "POST", body: JSON.stringify({ outcome }),
      });
      await qc.invalidateQueries({ queryKey: ["sessions"] });
    } catch (e) {
      console.error("resolve failed:", e);
    } finally {
      setResolving(null);
    }
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <h1 className="text-xl font-bold">审批中心</h1>

      {!openTasks.length && (
        <div className="rounded-xl border border-slate-200 bg-surface
                        p-8 text-center">
          <p className="text-sm text-slate-400">当前无待审批任务</p>
          <p className="text-xs text-slate-300 mt-1">
            当流程触发 human.task.create 时，任务将出现在此处</p>
        </div>
      )}

      {openTasks.map(t => (
        <div key={t.task_id}
          className="flex items-center justify-between rounded-xl
                     border border-amber-200 bg-amber-50 px-4 py-3">
          <div>
            <p className="text-sm font-medium">{t.task_id}</p>
            <p className="text-xs text-slate-500">
              类型: {t.task_type} · 会话: {t.session}</p>
          </div>
          <div className="flex gap-2">
            <button
              disabled={resolving === t.task_id}
              onClick={() => void resolve(t.task_id, "approve")}
              className="px-3 py-1.5 text-xs font-semibold text-white
                         bg-emerald-600 rounded hover:bg-emerald-700
                         disabled:opacity-50 transition-colors"
            >批准</button>
            <button
              disabled={resolving === t.task_id}
              onClick={() => void resolve(t.task_id, "reject")}
              className="px-3 py-1.5 text-xs font-semibold text-white
                         bg-red-500 rounded hover:bg-red-600
                         disabled:opacity-50 transition-colors"
            >驳回</button>
          </div>
        </div>
      ))}
    </div>
  );
}