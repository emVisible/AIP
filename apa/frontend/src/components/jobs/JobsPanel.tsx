/**
 * 定时任务管理（影刀「计划任务」对标）。
 * 列表 + cron 编辑弹窗 + 立即运行；变更即持久化 scheduler.yaml 并热生效。
 */
import { useCallback, useEffect, useState } from "react";
import { Clock, Pencil, Play, Plus, Trash2 } from "lucide-react";

import { Badge, Button, Card, Dialog, Field, IconButton, Input,
         Select } from "../ui";

interface JobSpec {
  id: string;
  kind: "cron" | "event" | "watch";
  process: string;
  expr?: string | null;
  event?: string | null;
  next_run?: string | null;
  next_error?: string | null;
  exists?: boolean;
}

interface JobsResp {
  jobs: JobSpec[];
  count: number;
}

export function JobsPanel() {
  const [jobs, setJobs] = useState<JobSpec[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState<null | {
    id: string; kind: "cron" | "event" | "watch";
    process: string; expr: string; event: string;
  }>(null);
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/jobs").then(x => x.json()) as JobsResp;
      setJobs(r.jobs ?? []);
      setLoaded(true);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function save(spec: typeof editing) {
    if (!spec) return;
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
      if (!r.ok) throw new Error(await r.text());
      setEditing(null);
      setMsg(`已保存 ${body.id} ✓`);
      await refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function remove(id: string) {
    try {
      await fetch(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
      setMsg(`已删除 ${id}`);
      await refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function runNow(id: string) {
    try {
      await fetch(`/api/jobs/${encodeURIComponent(id)}/run`,
                  { method: "POST" });
      setMsg(`${id} 已触发，结果见运行历史`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between px-3 py-2
                      border-b border-slate-100">
        <span className="flex items-center gap-1.5 text-xs font-semibold
                         text-slate-700">
          <Clock size={13} /> 定时任务 ({jobs.length})
        </span>
        <Button size="sm" variant="secondary"
                onClick={() => setEditing(
                  { id: "", kind: "cron", process: "",
                    expr: "0 * * * *", event: "" })}>
          <Plus size={13} /> 新建
        </Button>
      </div>

      <div className="divide-y divide-slate-50">
        {jobs.map(j => (
          <div key={j.id} className="flex items-center gap-2 px-3 py-2
                                     hover:bg-slate-50/60">
            <Badge tone={j.kind === "cron" ? "blue"
                       : j.kind === "watch" ? "amber" : "violet"}>
              {j.kind}
            </Badge>
            <span className="font-mono text-xs text-slate-700">{j.id}</span>
            <span className="font-mono text-[10px] text-slate-400 truncate">
              {j.kind === "cron" ? j.expr : j.event}
            </span>
            {!j.exists && <Badge tone="red">流程缺失</Badge>}
            <span className="ml-auto text-[10px] text-slate-400">
              {j.next_run ? `下次 ${j.next_run}` : ""}
              {j.next_error ? "cron 无效" : ""}
            </span>
            <IconButton label="立即运行" onClick={() => void runNow(j.id)}>
              <Play size={12} />
            </IconButton>
            <IconButton label="编辑" onClick={() => setEditing({
              id: j.id, kind: j.kind, process: j.process,
              expr: j.expr ?? "0 * * * *", event: j.event ?? "" })}>
              <Pencil size={12} />
            </IconButton>
            <IconButton label="删除"
                        className="hover:text-red-600"
                        onClick={() => void remove(j.id)}>
              <Trash2 size={12} />
            </IconButton>
          </div>
        ))}
        {loaded && !jobs.length && (
          <p className="px-3 py-4 text-xs text-slate-400">
            暂无任务——新建一个 cron 或事件触发任务</p>
        )}
        {!loaded && (
          <p className="px-3 py-4 text-xs text-slate-400">加载中…</p>
        )}
      </div>

      {/* 编辑弹窗 */}
      <Dialog open={!!editing} onClose={() => setEditing(null)} width={480}>
        {editing && (
          <>
            <div className="px-4 py-3 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-800">
                {editing.id ? `编辑任务 ${editing.id}` : "新建任务"}
              </h2>
            </div>
            <div className="px-4 py-3 space-y-3 max-h-[60vh] overflow-y-auto">
              <Field label="任务 ID">
                <Input value={editing.id}
                       disabled={!!jobs.find(j => j.id === editing.id)}
                       onChange={e => setEditing({ ...editing,
                                                   id: e.target.value })} />
              </Field>
              <Field label="触发方式">
                <Select value={editing.kind}
                        onChange={e => setEditing({ ...editing,
                          kind: e.target.value as JobSpec["kind"] })}>
                  <option value="cron">定时 (cron)</option>
                  <option value="event">事件</option>
                  <option value="watch">文件监听</option>
                </Select>
              </Field>
              {editing.kind === "watch" ? (
                <Field label="监听路径 (glob)" hint="相对当前目录">
                  <Input value={editing.expr} className="font-mono"
                         placeholder="data/inbox/*.csv"
                         onChange={e => setEditing({ ...editing,
                                                     expr: e.target.value })} />
                </Field>
              ) : editing.kind === "cron" ? (
                <Field label="Cron 表达式" hint="分 时 日 月 周">
                  <Input value={editing.expr} className="font-mono"
                         placeholder="0 9 * * *"
                         onChange={e => setEditing({ ...editing,
                                                     expr: e.target.value })} />
                </Field>
              ) : (
                <Field label="事件名" hint="三段式 a.b.c">
                  <Input value={editing.event} className="font-mono"
                         placeholder="erp.order.created"
                         onChange={e => setEditing({ ...editing,
                                                     event: e.target.value })} />
                </Field>
              )}
              <Field label="流程 ID">
                <Input value={editing.process} className="font-mono"
                       placeholder="process 文件名"
                       onChange={e => setEditing({ ...editing,
                                                   process: e.target.value })} />
              </Field>
            </div>
            <div className="flex justify-end gap-2 px-4 py-2.5 border-t
                            border-slate-100 bg-slate-50/50">
              <Button size="sm" variant="ghost"
                      onClick={() => setEditing(null)}>取消</Button>
              <Button size="sm" variant="primary"
                      onClick={() => void save(editing)}>保存</Button>
            </div>
          </>
        )}
      </Dialog>

      {msg && <p className="px-3 py-1.5 text-[10px] text-slate-500">{msg}</p>}
    </Card>
  );
}