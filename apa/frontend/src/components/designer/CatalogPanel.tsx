import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { ActionMeta } from "../../api/types";
import { cn } from "../../lib/utils";

/** 动作目录侧栏 —— 单一职责：展示+搜索+选中回调。 */
export function CatalogPanel({ onInsert }: { onInsert: (action: string) => void }) {
  const [filter, setFilter] = useState("");

  const { data: catalog = {} } = useQuery({
    queryKey: ["registry", "actions"],
    queryFn: () => fetch("/api/registry/actions").then((r) => r.json()),
  });

  const groups = useMemo(() => {
    const q = filter.toLowerCase();
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
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="max-h-[400px] overflow-y-auto">
        {Object.entries(groups).map(([domain, items]) => (
          <div key={domain}>
            <p className="text-[10px] font-semibold text-slate-400 uppercase
                          tracking-wide px-1 pt-2">{domain}</p>
            {items.map(([name, meta]) => (
              <div
                key={name}
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