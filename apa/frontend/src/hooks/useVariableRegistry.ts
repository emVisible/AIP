/**
 * 变量注册表 —— 追踪流水线中每一步的输出变量。
 *
 * 设计模式：观察者 + 注册表。步骤变化时自动重新计算可用变量集，
 * 供 SchemaForm 的变量选择器使用。
 */
import type { DStep } from "../types/designer";

export interface VariableInfo {
  /** 变量路径，如 steps.fetch_order.order_id */
  path: string;
  /** 来源步骤 ID */
  stepId: string;
  /** 来源步骤的动作名 */
  sourceAction: string;
  /** 值预览 */
  preview: string;
}

/** 从步骤的 params 中提取所有叶子字段作为输出变量。 */
function extractOutputVars(step: DStep): VariableInfo[] {
  const out: VariableInfo[] = [];
  const stepId = step.id || "unnamed";
  const action = step.action || "";

  try {
    const params = JSON.parse(step.params_json || "{}");
    for (const [key, val] of Object.entries(params)) {
      const v = val as unknown;
      out.push({
        path: `${stepId}.${key}`,
        stepId,
        sourceAction: action,
        preview: typeof v === "string" ? v : JSON.stringify(v),
      });
    }
  } catch { /* bad JSON → skip */ }

  // output_as 别名也注册
  if (step.output_as) {
    out.push({
      path: step.output_as,
      stepId,
      sourceAction: action,
      preview: `output_as:${step.output_as}`,
    });
  }

  return out;
}

/** 触发事件的隐式变量（始终可用）。 */
export const TRIGGER_VARS: VariableInfo[] = [
  { path: "event.name", stepId: "__trigger__", sourceAction: "trigger", preview: "触发事件名" },
  { path: "event.data", stepId: "__trigger__", sourceAction: "trigger", preview: "事件数据" },
  { path: "event.data.context", stepId: "__trigger__", sourceAction: "trigger", preview: "上下文引用" },
];

/**
 * 计算在第 stepIndex 步时可用的所有变量。
 * 包含触发事件变量 + 前面所有步骤的输出。
 */
export function availableVariables(
  steps: DStep[],
  upToIndex: number,
): VariableInfo[] {
  const vars = [...TRIGGER_VARS];
  for (let i = 0; i < Math.min(upToIndex, steps.length); i++) {
    vars.push(...extractOutputVars(steps[i]!));
  }
  return vars;
}

/** 在字符串中查找 {{var}} 引用并检查是否可解析。 */
export function findUnresolvedRefs(
  template: string,
  available: VariableInfo[],
): string[] {
  const paths = new Set(available.map(v => v.path));
  const unresolved: string[] = [];
  const pattern = /\{\{\s*([^}]+?)\s*\}\}/g;
  let m: RegExpExecArray | null = null;
  while ((m = pattern.exec(template))) {
    const expr = m[1] ?? "";
    const root = expr.replace(/^steps\./, "").split(".")[0] ?? "";
    if (!paths.has(root) && !root.startsWith("event.")) {
      unresolved.push(expr);
    }
  }
  return unresolved;
}