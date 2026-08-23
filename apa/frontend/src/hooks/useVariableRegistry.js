/** 从步骤的 params 中提取所有叶子字段作为输出变量。 */
function extractOutputVars(step) {
    const out = [];
    const stepId = step.id || "unnamed";
    const action = step.action || "";
    try {
        const params = JSON.parse(step.params_json || "{}");
        for (const [key, val] of Object.entries(params)) {
            const v = val;
            out.push({
                path: `${stepId}.${key}`,
                stepId,
                sourceAction: action,
                preview: typeof v === "string" ? v : JSON.stringify(v),
            });
        }
    }
    catch { /* bad JSON → skip */ }
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
export const TRIGGER_VARS = [
    { path: "event.name", stepId: "__trigger__", sourceAction: "trigger", preview: "触发事件名" },
    { path: "event.data", stepId: "__trigger__", sourceAction: "trigger", preview: "事件数据" },
    { path: "event.data.context", stepId: "__trigger__", sourceAction: "trigger", preview: "上下文引用" },
];
/**
 * 计算在第 stepIndex 步时可用的所有变量。
 * 包含触发事件变量 + 前面所有步骤的输出。
 */
export function availableVariables(steps, upToIndex) {
    const vars = [...TRIGGER_VARS];
    for (let i = 0; i < Math.min(upToIndex, steps.length); i++) {
        vars.push(...extractOutputVars(steps[i]));
    }
    return vars;
}
/** 在字符串中查找 {{var}} 引用并检查是否可解析。 */
export function findUnresolvedRefs(template, available) {
    const paths = new Set(available.map(v => v.path));
    const unresolved = [];
    const pattern = /\{\{\s*([^}]+?)\s*\}\}/g;
    let m = null;
    while ((m = pattern.exec(template))) {
        const expr = m[1] ?? "";
        const root = expr.replace(/^steps\./, "").split(".")[0] ?? "";
        if (!paths.has(root) && !root.startsWith("event.")) {
            unresolved.push(expr);
        }
    }
    return unresolved;
}
