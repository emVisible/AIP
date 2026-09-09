/**
 * 画布步骤节点视觉（M3 自 DesignerPage 抽出，UI 重构升级）。
 *
 * 结构：左侧类型色条 + 序号徽标 + 中文标题行 + 副行（动作名或类型徽标）
 *       + 可选参数摘要行；交互（选中/删除）由画布层 onNodeClick 处理。
 */
import { Handle, Position } from "@xyflow/react";
import { Boxes, Repeat, Sparkles } from "lucide-react";

export type StepNodeData = {
  /** 主标题：中文功能名（actionDisplay 统一出口）。 */
  title: string;
  /** 副标题：原始动作名 mono；纯 type 节点为 null。 */
  sub?: string | null;
  /** 参数摘要一行（k=v · k=v）。 */
  summary?: string;
  tone: string;
  index?: number;
  kind?: "" | "foreach" | "sub_process" | "ai_decision" | "while" | "log";
  /** 条件跳过（condition 非空）。P1-T3：徽标与数据一一对应。 */
  hasCondition?: boolean;
  /** 失败跳转（on_failure_goto 指向现存步骤）。 */
  hasGoto?: boolean;
  /** 循环体内步骤数（body_steps.length，无则不显示）。P1-T5。 */
  loopCount?: number;
};

const KIND_ACCENT: Record<string, string> = {
  "": "bg-slate-300",
  foreach: "bg-violet-400",
  while: "bg-violet-400",
  sub_process: "bg-sky-400",
  ai_decision: "bg-fuchsia-400",
  log: "bg-emerald-300",
};

const KIND_ICON: Record<string, typeof Repeat> = {
  foreach: Repeat,
  while: Repeat,
  sub_process: Boxes,
  ai_decision: Sparkles,
};

/** 类型徽标文案（无 action 的内建控制流节点）。 */
const KIND_BADGE: Record<string, string> = {
  foreach: "循环",
  while: "循环",
  sub_process: "子流程",
  ai_decision: "AI",
  log: "日志",
};

/** 画布步骤节点：白底卡片 + 左侧类型色条 + 序号徽标。 */
export function StepNodeView({ data }: { data: StepNodeData }) {
  const kind = data.kind ?? "";
  const accent = KIND_ACCENT[kind] ?? KIND_ACCENT[""]!;
  const KindIcon = KIND_ICON[kind];
  const badge = !data.sub && KIND_BADGE[kind];
  return (
    <div className={`relative rounded-lg border bg-white px-3 py-2
                     min-w-[180px] max-w-[240px]
                     shadow-[0_1px_3px_rgba(0,0,0,0.08)]
                     transition-[box-shadow,border-color] duration-150
                     cursor-grab active:cursor-grabbing
                     hover:shadow-[0_2px_8px_rgba(0,0,0,0.10)]
                     ${data.tone}`}>
      <span className={`absolute left-0 top-2 bottom-2 w-[3px] rounded-full
                        ${accent}`} />
      <div className="flex items-center gap-1.5">
        {data.index != null && (
          <span className="inline-flex items-center justify-center w-4 h-4
                           shrink-0 rounded-full bg-zinc-900 text-white
                           text-[9px] font-semibold leading-none">
            {data.index + 1}
          </span>
        )}
        <p className="text-xs font-semibold text-slate-800 truncate">
          {data.title}
        </p>
        {KindIcon && <KindIcon size={11} className="shrink-0 text-slate-300" />}
      </div>
      {(data.sub || badge) && (
        <div className="mt-0.5 flex items-center gap-1.5 min-w-0">
          {badge ? (
            <span className="text-[9px] leading-none rounded
                             bg-violet-50 text-violet-500 px-1 py-0.5
                             font-medium shrink-0">
              {badge}
            </span>
          ) : null}
          {data.sub && (
            <p className="text-[10px] text-slate-400 truncate font-mono
                          leading-tight">
              {data.sub}
            </p>
          )}
        </div>
      )}
      {data.summary && (
        <p className="mt-0.5 text-[10px] text-slate-300 truncate
                      leading-tight">
          {data.summary}
        </p>
      )}
      {(data.hasCondition || data.hasGoto || (data.loopCount ?? 0) > 0) && (
        <div className="mt-1 flex items-center gap-1 animate-fade-in">
          {data.hasCondition && (
            <span title="条件跳过：condition 非空"
              className="text-[9px] leading-none rounded bg-amber-50
                         text-amber-600 px-1 py-0.5 font-medium">
              ⏭ 条件
            </span>
          )}
          {data.hasGoto && (
            <span title="失败跳转：on_failure_goto"
              className="text-[9px] leading-none rounded bg-rose-50
                         text-rose-600 px-1 py-0.5 font-medium">
              ⚠ 跳转
            </span>
          )}
          {(data.loopCount ?? 0) > 0 && (
            <span title="循环体内步骤数"
              className="text-[9px] leading-none rounded bg-violet-50
                         text-violet-600 px-1 py-0.5 font-medium">
              ↻ 体内×{data.loopCount}
            </span>
          )}
        </div>
      )}
      <Handle type="target" position={Position.Top} className="!w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Bottom} className="!w-1.5 !h-1.5" />
    </div>
  );
}

export const nodeTypes = { step: StepNodeView };
