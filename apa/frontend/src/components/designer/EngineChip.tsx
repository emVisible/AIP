/**
 * 决策引擎状态 chip（设计器顶栏）。
 * rules_only 灰 / cascade_llm 蓝 / dsh 绿；数据源 /api/ai/status。
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";

export function EngineChip() {
  const [mode, setMode] = useState("...");
  useEffect(() => {
    api<{ mode: string }>("/api/ai/status")
      .then(d => setMode(d.mode))
      .catch(() => setMode("offline"));
  }, []);
  const tone = mode === "dsh" ? "bg-emerald-50 text-emerald-600"
    : mode === "cascade_llm" ? "bg-blue-50 text-blue-600"
    : "bg-slate-100 text-slate-500";
  const label = mode === "dsh" ? "DSH"
    : mode === "cascade_llm" ? "L0+LLM" : "规则";
  return (
    <span title={`决策引擎: ${mode}`} data-mode={mode}
          className={`inline-flex items-center h-6 px-2 rounded-md
                      text-[10px] font-medium ${tone}`}>
      {label}
    </span>
  );
}
