import { useDesignerStore } from "../../pages/designer/designerStore";

/** 属性面板：选中步骤的参数编辑（职责单一：只编辑当前选中项）。 */
export function ParamsPanel() {
  const { steps, selectedIdx, updateStep } = useDesignerStore();
  const step = selectedIdx != null ? steps[selectedIdx] : undefined;

  if (!step) {
    return <p className="text-xs text-slate-400 p-3">点击画布中的步骤节点以编辑属性</p>;
  }

  const field = (key: keyof typeof step, label: string,
                 placeholder?: string) => (
    <div>
      <label className="text-[11px] text-slate-400">{label}</label>
      <input
        className="w-full px-2 py-1 text-xs border border-slate-200 rounded"
        value={((step as unknown as Record<string, unknown>)[key] as string) ?? ""}
        placeholder={placeholder}
        onChange={(e) => updateStep(selectedIdx!, { [key]: e.target.value })}
      />
    </div>
  );

  return (
    <div className="space-y-2 p-1">
      <p className="text-[10px] font-semibold text-slate-400 uppercase">
        步骤属性 — {step.id}
      </p>
      {field("id", "步骤 ID")}
      {field("action", "动作名")}
      {field("target", "target（可选）")}

      <div>
        <label className="text-[11px] text-slate-400">参数 (JSON)</label>
        <textarea
          className="w-full px-2 py-1 text-xs font-mono border border-slate-200
                     rounded resize-y"
          rows={4}
          value={step.params_json}
          onChange={(e) =>
            updateStep(selectedIdx!, { params_json: e.target.value })}
        />
      </div>

      {field("condition", "condition（原始表达式，留空跳过）")}
      {field("output_as", "output_as（结果别名）")}
      {field("on_failure_goto", "失败 goto key（可选）")}
    </div>
  );
}