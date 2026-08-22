import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn 惯例：合并 Tailwind 类并解决冲突。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 会话/任务状态 → 语义色（单一权威，视图只消费映射结果）。 */
export const STATE_TONE: Record<string, string> = {
  RUNNING: "text-blue-600 bg-blue-50 border-blue-200",
  COMPLETED: "text-emerald-600 bg-emerald-50 border-emerald-200",
  FAILED: "text-red-600 bg-red-50 border-red-200",
  CANCELLED: "text-slate-500 bg-slate-100 border-slate-200",
  SUSPENDED: "text-amber-600 bg-amber-50 border-amber-200",
  INITIALIZING: "text-slate-500 bg-slate-100 border-slate-200",
};

export function stateTone(state: string): string {
  return STATE_TONE[state] ?? "text-slate-500 bg-slate-100 border-slate-200";
}
