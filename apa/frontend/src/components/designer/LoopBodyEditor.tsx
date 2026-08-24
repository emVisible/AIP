/**
 * 循环体编辑器（P20-C）—— foreach 步骤的子步骤可视化列表。
 *
 * 单一职责：body_steps 数组的增/删/上下移/参数编辑。
 * 子步骤参数用紧凑 JSON 文本域（与主画布卡片同级复杂度），
 * 不嵌套弹窗 —— 避免弹窗中弹窗。
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import type { DStep } from "../../types/designer";
import { Button, IconButton, Input, Textarea } from "../ui";

export function LoopBodyEditor({ steps: bodySteps, onChange }: {
  steps: DStep[];
  onChange: (next: DStep[]) => void;
}) {
  function update(i: number, patch: Partial<DStep>) {
    onChange(bodySteps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  }

  function remove(i: number) {
    onChange(bodySteps.filter((_, j) => j !== i));
  }

  function move(i: number, dir: -1 | 1) {
    const to = i + dir;
    if (to < 0 || to >= bodySteps.length) return;
    const next = [...bodySteps];
    const [m] = next.splice(i, 1);
    next.splice(to, 0, m!);
    onChange(next);
  }

  function add() {
    onChange([...bodySteps, {
      id: `b${bodySteps.length + 1}`,
      type: "", action: "", target: "",
      params_json: "{}", condition: "", output_as: "",
      on_failure_goto: "",
    }]);
  }

  return (
    <div className="space-y-1.5">
      {!bodySteps.length && (
        <p className="text-[10px] text-slate-400">
          循环体为空——添加至少一个步骤（每轮迭代按顺序执行）</p>
      )}
      {bodySteps.map((s, i) => (
        <div key={i} className="rounded-md border border-slate-200 bg-white
                                px-2 py-1.5 space-y-1">
          <div className="flex items-center gap-1">
            <span className="text-[10px] font-semibold text-slate-400
                             w-4">{i + 1}</span>
            <Input className="h-6 flex-1 text-[11px] font-mono"
                   placeholder="action 名"
                   value={s.action}
                   onChange={(e) => update(i, { action: e.target.value })} />
            <Input className="h-6 w-20 text-[11px] font-mono"
                   placeholder="id"
                   value={s.id}
                   onChange={(e) => update(i, { id: e.target.value })} />
            <IconButton label="上移" onClick={() => move(i, -1)}
                        disabled={i === 0}>
              <ArrowUp size={11} />
            </IconButton>
            <IconButton label="下移" onClick={() => move(i, 1)}
                        disabled={i === bodySteps.length - 1}>
              <ArrowDown size={11} />
            </IconButton>
            <IconButton label="删除" onClick={() => remove(i)}
                        className="hover:text-red-600">
              <Trash2 size={11} />
            </IconButton>
          </div>
          <Textarea rows={2}
            className="font-mono text-[10px]"
            placeholder='{"target": "{{row.id}}"}'
            value={s.params_json}
            onChange={(e) => update(i, { params_json: e.target.value })} />
          {s.condition && (
            <p className="text-[10px] text-amber-500 truncate">
              条件 {s.condition}
            </p>
          )}
        </div>
      ))}
      <Button size="sm" variant="ghost" onClick={add}
              className="w-full border border-dashed border-slate-300">
        <Plus size={12} /> 添加循环体步骤
      </Button>
    </div>
  );
}