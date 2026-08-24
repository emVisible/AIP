import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ActionMeta } from "../../api/types";
import { cn } from "../../lib/utils";

/** 流程控制特殊节点（非 registry 动作，由 ProcessEngine 内建解释）。 */
export const FLOW_NODES: [string, string][] = [
  ["flow.foreach", "循环：遍历数组逐项执行 body_action"],
  ["flow.sub_process", "子流程：调用另一个 process.yaml"],
  ["flow.ai_decision", "AI 决策：LLM 从候选动作中选择 outcome"],
];

/** 动作目录侧栏 —— 单一职责：展示+搜索+选中回调。 */
export function CatalogPanel({ onInsert, filter, onFilterChange }: {
  onInsert: (action: string) => void;
  /** 受控搜索词（状态提升：左栏 Tab 切换不丢失） */
  filter?: string;
  onFilterChange?: (v: string) => void;
}) {
  const [inner, setInner] = useState("");
  const filter_ = filter ?? inner;
  const setFilter = onFilterChange ?? setInner;

  const { data: catalog = {} } = useQuery({
    queryKey: ["registry", "actions"],
    queryFn: () => fetch("/api/registry/actions").then((r) => r.json()),
  });

  const flowItems = useMemo(() => {
    const q = filter_.toLowerCase();
    return FLOW_NODES.filter(([n, d]) =>
      !q || n.toLowerCase().includes(q) || d.toLowerCase().includes(q));
  }, [filter]);

  const groups = useMemo(() => {
    const q = filter_.toLowerCase();
    const byDomain: Record<string, [string, ActionMeta][]> = {};
    for (const [name, meta] of Object.entries(
      catalog as Record<string, ActionMeta>,
    )) {
      if (q && !name.toLowerCase().includes(q) &&
          !(meta.description ?? "").toLowerCase().includes(q)) {
        continue;
      }
      const domain = name.split(".")[0] ?? "other";
      (byDomain[domain] ??= []).push([name, meta]);
    }
    return byDomain;
  }, [catalog, filter]);

  return (
    <div className="space-y-1">
      <input
        className="w-full px-2 py-1 text-xs border border-slate-200 rounded"
        placeholder="搜索动作…"
        value={filter_}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="max-h-[400px] overflow-y-auto">
        {flowItems.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-slate-400 uppercase
                          tracking-wide px-1 pt-2">流程控制</p>
            {flowItems.map(([name, desc]) => (
              <div key={name}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/apa-action", name);
                  // U2: Firefox 需 text/plain 才稳定启动 DnD 会话
                  e.dataTransfer.setData("text/plain", name);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                onClick={() => onInsert(name)}
                className="px-2 py-1 cursor-pointer rounded text-xs
                           hover:bg-violet-50 flex justify-between items-center"
                title={desc}>
                <span className="font-mono truncate text-violet-700">{name}</span>
                <span className="text-[10px] rounded px-1 bg-violet-100
                                 text-violet-600">CTL</span>
              </div>
            ))}
          </div>
        )}
        {Object.entries(groups).map(([domain, items]) => (
          <div key={domain}>
            <p className="text-[10px] font-semibold text-slate-400 uppercase
                          tracking-wide px-1 pt-2">{domain}</p>
            {items.map(([name, meta]) => (
              <div
                key={name}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/apa-action", name);
                  // U2: Firefox 需 text/plain 才稳定启动 DnD 会话
                  e.dataTransfer.setData("text/plain", name);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                onClick={() => onInsert(name)}
                className={cn(
                  "px-2 py-1 cursor-pointer rounded text-xs hover:bg-blue-50",
                  "flex justify-between items-center",
                )}
                title={meta.description ?? ""}
              >
                <span className="font-mono truncate">{name}</span>
                <span
                  className={`text-[10px] rounded px-1 ${
                    meta.risk.startsWith("L0") ? "text-slate-400"
                    : meta.risk.startsWith("L1") || meta.risk.startsWith("L2")
                      ? "text-amber-500" : "text-red-500"
                  }`}
                >{meta.risk}</span>
              </div>
            ))}
          </div>
        ))}
        {!Object.keys(groups).length && (
          <p className="text-xs text-slate-400 p-2">（无匹配动作）</p>
        )}
      </div>
    </div>
  );
}