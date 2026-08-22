import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

import type { DesignerStep } from "../../pages/designer/designerTypes";

export type StepNodeData = { step: DesignerStep; selected: boolean };

/** 自定义步骤节点 —— 职责单一：仅渲染，交互由画布层处理。 */
export function StepNode({ data }: NodeProps) {
  const { step, selected } = (data as unknown) as StepNodeData;
  const isAI = step.type === "ai_decision";

  const tone = selected
    ? "border-brand ring-2 ring-blue-200"
    : isAI
      ? "border-purple-300 bg-purple-50"
      : "border-slate-300 bg-white";

  return (
    <div className={`rounded-lg border px-3 py-2 min-w-[140px] shadow-sm ${tone}`}>
      <Handle type="target" position={Position.Top} className="!w-1.5 !h-1.5" />
      <p className={`text-xs font-semibold ${isAI ? "text-purple-700" : "text-slate-700"}`}>
        {isAI ? "⚡ " : ""}{step.id}
      </p>
      {step.action && (
        <p className="text-[11px] text-slate-500 mt-0.5 truncate">{step.action}</p>
      )}
      {step.condition && (
        <p className="text-[10px] text-amber-600 mt-0.5 truncate">
          ? {step.condition}
        </p>
      )}
      <Handle type="source" position={Position.Bottom} className="!w-1.5 !h-1.5" />
    </div>
  );
}