import { useEffect, useState } from "react";

import type { ActionMeta } from "../api/types";

export function Settings() {
  const [actions, setActions] = useState<Record<string, ActionMeta>>({});
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetch("/api/registry/actions")
      .then(r => r.json())
      .then(setActions)
      .catch(() => {});
  }, []);

  const filtered = Object.entries(actions).filter(
    ([name]) => !filter || name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-4 max-w-4xl">
      <h1 className="text-xl font-bold">设置</h1>

      {/* 动作注册表浏览 */}
      <div className="rounded-xl border border-slate-200 bg-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center
                        justify-between">
          <h2 className="text-sm font-semibold">
            Action Registry（{Object.keys(actions).length} 个动作）</h2>
          <input
            className="w-48 px-2 py-1 text-xs border rounded"
            placeholder="搜索…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left
                           text-slate-500">
              <th className="px-4 py-2 font-medium">动作名</th>
              <th className="px-4 py-2 font-medium">风险</th>
              <th className="px-4 py-2 font-medium">域</th>
              <th className="px-4 py-2 font-medium">幂等性</th>
              <th className="px-4 py-2 font-medium">描述</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(([name, meta]) => (
              <tr key={name} className="border-b border-slate-50 hover:bg-slate-50">
                <td className="px-4 py-1.5 font-mono">{name}</td>
                <td className="px-4 py-1.5">
                  <span className={`rounded px-1.5 ${
                    meta.risk.startsWith("L0") ? "bg-emerald-50 text-emerald-600"
                    : meta.risk.startsWith("L1") ? "bg-blue-50 text-blue-600"
                    : meta.risk.startsWith("L2") ? "bg-amber-50 text-amber-600"
                    : "bg-red-50 text-red-600"
                  }`}>{meta.risk}</span>
                </td>
                <td className="px-4 py-1.5">{meta.executor_domain}</td>
                <td className="px-4 py-1.5">{meta.idempotency}</td>
                <td className="px-4 py-1.5 text-slate-400">
                  {meta.description.slice(0, 40)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 租户 / 认证信息占位（M3 增强） */}
      <div className="rounded-xl border border-slate-200 bg-surface p-4 space-y-2">
        <h2 className="text-sm font-semibold">租户与认证</h2>
        <p className="text-xs text-slate-400">
          多租户管理与认证配置将在 M3 产品化阶段提供完整 UI。
        </p>
      </div>
    </div>
  );
}