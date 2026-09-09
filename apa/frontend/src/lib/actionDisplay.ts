/**
 * 动作显示规则 —— 中文功能名优先的单一出口。
 *
 * 真相源分层：
 *   registry 动作 → registries/*.yaml 的 label_cn（后端经 studioRpc registry.actions 下发）
 *   流程控制节点  → 本文件 FLOW_LABELS（前端内建节点，不在 registry）
 *
 * 所有展示面（动作目录 / 步骤列表 / 画布节点 / 属性面板）统一经此取标题，
 * 禁止各自回退拼接——否则中文缺失时会出现 API 接口名直出的体验。
 */
import type { ActionMeta } from "../api/types";
import { getLanguage } from "../hooks/useLanguage";

/** 流程控制节点中文名（ProcessEngine 内建解释，非 registry 动作）。 */
export const FLOW_LABELS: Record<string, string> = {
  "flow.foreach": "循环遍历",
  "flow.sub_process": "子流程",
  "flow.ai_decision": "AI 决策",
};

/** 流程控制节点目录元数据：名称 + 中文说明（目录 tooltip 用）。 */
export const FLOW_NODES: [string, string][] = [
  ["flow.foreach", "循环：遍历数组逐项执行 body_action"],
  ["flow.sub_process", "子流程：调用另一个 process.yaml"],
  ["flow.ai_decision", "AI 决策：LLM 从候选动作中选择 outcome"],
];

/**
 * 主标题：中文功能名；语言为 en 或数据缺失时回退原始动作名。
 * flow.* 前端内建节点同样覆盖。
 */
export function actionTitle(
  action: string,
  catalog?: Record<string, ActionMeta>,
): string {
  if (!action) return "";
  if (getLanguage() === "zh") {
    const flow = FLOW_LABELS[action];
    if (flow) return flow;
    return catalog?.[action]?.label_cn || action;
  }
  return action;
}

/** 副标题：原始动作名；与主标题相同（无中文）时返回 null 不展示。 */
export function actionSub(
  action: string,
  catalog?: Record<string, ActionMeta>,
): string | null {
  if (!action) return null;
  return actionTitle(action, catalog) === action ? action : null;
}

/**
 * 内建类型节点中文名（step.type 驱动：foreach/while 等由引擎解释，
 * stepFromAction 创建时 action 为空，registry 查不到）。
 */
const TYPE_LABELS: Record<string, string> = {
  foreach: "循环遍历",
  while: "条件循环",
  sub_process: "子流程",
  ai_decision: "AI 决策",
  log: "日志输出",
};

/** 步骤主标题：action 优先（含 flow.*），其次 type 内建名。 */
export function stepTitle(
  step: { action: string; type: string },
  catalog?: Record<string, ActionMeta>,
): string {
  if (step.action) return actionTitle(step.action, catalog);
  const t = TYPE_LABELS[step.type];
  if (t) return getLanguage() === "zh" ? t : step.type;
  return "";
}

/** 步骤副标题：有 action 时为原始动作名；纯 type 节点返回 null（用徽标展示）。 */
export function stepSub(step: { action: string; type: string }): string | null {
  return step.action ? actionSub(step.action) : null;
}
