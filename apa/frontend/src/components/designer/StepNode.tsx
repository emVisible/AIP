/**
 * 画布步骤节点视觉（M3 自 DesignerPage 抽出）。
 * 白底卡片 + 左侧类型色条 + 序号徽标；交互由画布层处理。
 */

import { Handle, Position } from "@xyflow/react";

export type StepNodeData = {
  label: string;
  label_cn?: string;
  sub?: string;
  tone: string;
  index?: number;
  kind?: "" | "foreach" | "sub_process" | "ai_decision" | "while" | "log";
};

const KIND_ACCENT: Record<string, string> = {
  "": "bg-slate-300",
  foreach: "bg-violet-400",
  while: "bg-violet-400",
  sub_process: "bg-sky-400",
  ai_decision: "bg-fuchsia-400",
  log: "bg-emerald-300",
};

/** 画布步骤节点：白底卡片 + 左侧类型色条 + 序号徽标。 */
export function StepNodeView({ data }: { data: StepNodeData }) {
  const accent = KIND_ACCENT[data.kind ?? ""] ?? KIND_ACCENT[""]!;
  return (
    <div className={`relative rounded-lg border bg-white pl-3 pr-3 py-2
                     min-w-[160px] shadow-[0_1px_3px_rgba(0,0,0,0.08)]
                     transition-shadow hover:shadow-[0_2px_8px_rgba(0,0,0,0.10)]
                     ${data.tone}`}>
      <span className={`absolute left-0 top-2 bottom-2 w-[3px] rounded-full
                        ${accent}`} />
      <div className="flex items-center gap-1.5">
        {data.index != null && (
          <span className="inline-flex items-center justify-center w-4 h-4
                           rounded-full bg-zinc-900 text-white text-[9px]
                           font-semibold leading-none">
            {data.index + 1}
          </span>
        )}
        <p className="text-xs font-semibold text-slate-800 truncate">
          {data.label_cn || data.label}
        </p>
      </div>
      {data.sub && (
        <p className="mt-0.5 text-[10px] text-slate-400 truncate font-mono">
          {data.sub}
        </p>
      )}
      <Handle type="target" position={Position.Top} className="!w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Bottom} className="!w-1.5 !h-1.5" />
    </div>
  );
}

export const nodeTypes = { step: StepNodeView };
