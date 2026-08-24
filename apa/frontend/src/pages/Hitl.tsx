import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Hand } from "lucide-react";

import { Badge, Card, Button } from "../components/ui";
import { api } from "../api/client";
import { useSessions } from "../hooks/useSessions";

export function Hitl() {
  const qc = useQueryClient();
  const sessions = useSessions();
  const [resolving, setResolving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const openTasks = Object.values(sessions.data ?? {}).flatMap(
    (s) => s.tasks_open.map((t) => ({ ...t, session: s.id })),
  );

  async function resolve(taskId: string, outcome: string) {
    setResolving(taskId);
    setError(null);
    try {
      await api(`/tasks/${taskId}/resolve`, {
        method: "POST",
        body: JSON.stringify({ outcome }),
      });
      await qc.invalidateQueries({ queryKey: ["sessions"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResolving(null);
    }
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <header className="flex items-center gap-2.5">
        <Hand size={18} className="text-amber-500" />
        <h1 className="text-lg font-bold tracking-tight">审批中心</h1>
        {openTasks.length > 0 && (
          <Badge tone="amber">{openTasks.length} 待处理</Badge>
        )}
      </header>

      {!openTasks.length ? (
        <Card className="p-10 text-center">
          <Hand size={32} className="mx-auto text-slate-200 mb-3" />
          <p className="text-sm text-slate-500">当前无待审批任务</p>
          <p className="text-xs text-slate-300 mt-1">
            当流程触发 human.task.create 或 ui.confirm 时，
            审批卡片将出现在此处
          </p>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {openTasks.map((t) => (
            <Card key={t.task_id}
                  className="border-l-4 border-l-amber-400 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge tone={t.task_type === "confirm"
                      ? "blue" : "amber"}>
                      {t.task_type === "confirm" ? "确认" :
                       t.task_type === "exception" ? "异常" :
                       t.task_type}
                    </Badge>
                    <span className="font-mono text-xs text-slate-600
                                     truncate">
                      {t.task_id}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-slate-400 font-mono">
                    会话 {t.session}
                  </p>
                </div>
                <div className="flex gap-1.5 shrink-0">
                  <Button size="sm" variant="primary"
                          disabled={resolving === t.task_id}
                          onClick={() =>
                            void resolve(t.task_id, "approve")}>
                    批准
                  </Button>
                  <Button size="sm" variant="danger"
                          disabled={resolving === t.task_id}
                          onClick={() =>
                            void resolve(t.task_id, "reject")}>
                    驳回
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
}