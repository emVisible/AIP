/** 设计器拖放协议（HTML5 dataTransfer 类型与载荷约定）。 */
export const APA_ACTION_MIME = "application/apa-action";
export const APA_STEP_MIME = "application/apa-step-index";
/** 从 drag event 安全读取目录动作名。 */
export function readDnDAction(e) {
    return e.dataTransfer?.getData(APA_ACTION_MIME) || null;
}
/** 读取被拖动步骤卡的下标。 */
export function readDnDStepIndex(e) {
    const raw = e.dataTransfer?.getData(APA_STEP_MIME);
    if (raw === undefined || raw === "")
        return null;
    const n = Number(raw);
    return Number.isInteger(n) ? n : null;
}
