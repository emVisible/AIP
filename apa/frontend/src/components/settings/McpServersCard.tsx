/**
 * 外部 MCP 服务器卡（H7b）—— 单草稿模型。
 *
 * draft: {name: entry|null}；null = 待移除墓碑。
 * 保存时整段提交 mcp.servers（deep_merge 对 null 执行键删除）。
 */
import { useMemo, useState } from "react";

import { getIn, useSettings } from "../../hooks/useSettings";
import { Card, CardHeader, Button } from "../ui";

interface McpEntry { command: string[]; timeout_s?: number }

type DraftMap = Record<string, McpEntry | null>;

export function McpServersCard({ view, save }: {
  view: ReturnType<typeof useSettings>["view"];
  save: (patch: Record<string, any>) => Promise<string | null>;
}) {
  const servers: Record<string, McpEntry> =
    getIn(view?.settings, "mcp.servers") ?? {};
  const [draft, setDraft] = useState<DraftMap>({});
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const dirty = Object.keys(draft).length > 0;

  /** 展示视图：server 真值 + 草稿覆盖；null 墓碑过滤。 */
  const shown = useMemo(() => {
    const merged: Record<string, McpEntry | null> = { ...servers };
    for (const [k, v] of Object.entries(draft)) merged[k] = v;
    return Object.entries(merged)
      .filter(([, v]) => v !== null) as [string, McpEntry][];
  }, [servers, draft]);

  function setEntry(name: string, entry: McpEntry) {
    setDraft((d) => ({ ...d, [name]: entry }));
  }

  function markRemove(name: string) {
    setDraft((d) => ({ ...d, [name]: null }));
  }

  function undo(name: string) {
    setDraft((d) => {
      const n = { ...d };
      delete n[name];
      return n;
    });
  }

  async function persist() {
    if (!dirty) return;
    const err = await save({ mcp: { servers: draft } });
    if (!err) {
      setDraft({});
      setMsg("✓ 已保存并热应用");
      setTimeout(() => setMsg(null), 2500);
    } else {
      setMsg(`✗ ${err}`);
    }
  }

  return (
    <Card>
      <CardHeader title="外部 MCP 服务器"
        right={msg ? (
          <span className={`text-[10px] ${msg.startsWith("✓")
            ? "text-emerald-600" : "text-red-500"}`}>{msg}</span>
        ) : undefined} />
      <div className="p-3 space-y-2 text-xs">
        {!shown.length && (
          <p className="text-slate-400 leading-relaxed">
            尚未配置外部服务器。添加后即可经
            <code className="font-mono mx-1">mcp.tools_list</code>
            <code className="font-mono mx-1">mcp.tool_call</code>
            消费其工具。
          </p>
        )}

        {shown.map(([name, entry]) => {
          const d = draft[name];
          return (
            <div key={name}
                 className="border border-slate-100 rounded-md p-2 space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold text-sky-700">
                  {name}
                </span>
                <div className="ml-auto flex gap-1">
                  {d === null ? (
                    <button onClick={() => undo(name)}
                      className="text-[10px] px-1.5 py-0.5 border rounded
                                 hover:bg-slate-50">撤销移除</button>
                  ) : (
                    <button onClick={() => markRemove(name)}
                      className="text-[10px] px-1.5 py-0.5 border rounded
                                 hover:bg-red-50 text-red-500">移除</button>
                  )}
                </div>
              </div>
              {d !== null && (
                <input
                  className="w-full px-2 py-1 font-mono text-[10px] border
                             border-slate-200 rounded outline-none
                             focus:border-sky-400"
                  value={(draft[name] ?? entry).command.join(" ")}
                  placeholder="启动命令（空格分隔）"
                  onChange={(e) => setEntry(name, {
                    command: e.target.value.split(/\s+/).filter(Boolean),
                    timeout_s:
                      (draft[name] ?? entry).timeout_s ?? 30,
                  })} />
              )}
            </div>
          );
        })}

        <details className="text-[10px] text-slate-400">
          <summary className="cursor-pointer hover:text-slate-600">
            ＋ 添加服务器
          </summary>
          <div className="mt-1.5 flex gap-1">
            <input value={newName} onChange={(e) => setNewName(e.target.value)}
              placeholder="名称，如 company-tools"
              className="flex-1 px-2 py-1 border border-slate-200 rounded
                         font-mono outline-none focus:border-sky-400" />
            <button
              onClick={() => {
                const n = newName.trim();
                if (!n || shown.some(([k]) => k === n)) return;
                setDraft((d) => ({ ...d, [n]: { command: [] } }));
                setNewName("");
              }}
              className="px-2 py-1 border border-sky-200 text-sky-600
                         rounded hover:bg-sky-50 shrink-0">创建</button>
          </div>
        </details>

        {dirty && (
          <Button variant="primary"
            className="w-full mt-1"
            onClick={() => void persist()}>
            保存全部修改（含移除）
          </Button>
        )}
      </div>
    </Card>
  );
}
