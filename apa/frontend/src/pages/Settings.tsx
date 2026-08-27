/**
 * 设置页 —— AI 配置子系统（H7b）+ Registry 浏览 + 租户占位。
 *
 * 数据流全部经 Studio RPC：settings.get/update、ai/status、
 * registry/actions（长尾 REST，渐进迁移）。
 */
import { useEffect, useState } from "react";

import type { ActionMeta } from "../api/types";
import { Badge, Card, CardHeader } from "../components/ui";
import { LlmCard, PolicyCards } from "../components/settings/AiConfigCards";
import { McpServersCard }
  from "../components/settings/McpServersCard";
import { useSettings } from "../hooks/useSettings";

export function Settings() {
  const [actions, setActions] = useState<Record<string, ActionMeta>>({});
  const [filter, setFilter] = useState("");
  const settings = useSettings();

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

      {/* ---- AI 配置（H7b 双写区）---- */}
      <div className="space-y-4">
        <LlmCard view={settings.view} save={settings.save} />
        <PolicyCards view={settings.view} save={settings.save} />
        <McpServersCard view={settings.view} save={settings.save} />
        {settings.error && (
          <p className="text-xs text-red-500">{settings.error}</p>
        )}
      </div>

      <Card>
        <CardHeader title="决策引擎状态" />
        <EnginePanel />
      </Card>

      {/* 动作注册表浏览 */}
      <div className="rounded-xl border border-slate-200 bg-surface
                      overflow-hidden">
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
              <tr key={name}
                  className="border-b border-slate-50 hover:bg-slate-50">
                <td className="px-4 py-1.5 font-mono">{name}</td>
                <td className="px-4 py-1.5">
                  <span className={`rounded px-1.5 ${
                    meta.risk.startsWith("L0")
                      ? "bg-emerald-50 text-emerald-600"
                      : meta.risk.startsWith("L1")
                        ? "bg-blue-50 text-blue-600"
                        : meta.risk.startsWith("L2")
                          ? "bg-amber-50 text-amber-600"
                          : "bg-red-50 text-red-600"
                  }`}>{meta.risk}</span>
                </td>
                <td className="px-4 py-1.5">{meta.executor_domain}</td>
                <td className="px-4 py-1.5">{meta.idempotency}</td>
                <td className="px-4 py-1.5 text-slate-400">
                  {(meta.description || "").slice(0, 40)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 租户 / 认证信息占位（M3 增强） */}
      <div className="rounded-xl border border-slate-200 bg-surface p-4
                      space-y-2">
        <h2 className="text-sm font-semibold">租户与认证</h2>
        <p className="text-xs text-slate-400">
          多租户管理与认证配置将在 M3 产品化阶段提供完整 UI。
        </p>
      </div>
    </div>
  );
}

interface AiStatus {
  mode: string;
  model?: string;
}

/** 决策引擎实时模式（只读）。 */
function EnginePanel() {
  const [st, setSt] = useState<AiStatus | null>(null);

  useEffect(() => {
    fetch("/api/ai/status")
      .then((r) => r.json())
      .then(setSt)
      .catch(() => {});
  }, []);

  const mode = st?.mode ?? "unknown";
  const tone = mode === "dsh" ? "green"
    : mode === "cascade_llm" ? "blue" : "neutral";
  const label = mode === "dsh" ? "DSH 已接入"
    : mode === "cascade_llm" ? "级联决策 (L0 规则 + LLM)"
    : mode === "rules_only" ? "仅规则 (L0)" : mode;

  return (
    <div className="px-3 py-3 space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-slate-500">当前模式</span>
        <Badge tone={tone as never}>{label}</Badge>
        {st?.model && (
          <span className="font-mono text-[10px] text-slate-400">
            {st.model}
          </span>
        )}
      </div>
      <p className="text-[11px] leading-relaxed text-slate-400">
        模型/密钥请在上方「AI 模型与决策」卡配置；无密钥时 ai_decision
        节点自动转人工审批，全部功能离线可用。
      </p>
      <p className="text-[11px] leading-relaxed text-slate-400">
        外部 DSH 宿主：<code className="font-mono">
          node plugins/dsh/run-agent.mjs --gateway ws://127.0.0.1:8765
          --session &lt;会话&gt; --mock
        </code>
      </p>
    </div>
  );
}
