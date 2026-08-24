/**
 * StepEditDialog —— 影刀式步骤编辑弹窗。
 *
 * 单一职责：一个步骤的查看与编辑（第三部 2.1）。
 * 数据流：open 时从 step 快照初始化 draft → 编辑 → 保存时整体回写。
 * 表单主体复用 SchemaForm（schema 驱动 + 变量引用），本组件不感知字段语义。
 */
import { useEffect, useMemo, useState } from "react";
import { Trash2 } from "lucide-react";

import type { ActionMeta } from "../../api/types";
import type { VariableInfo } from "../../hooks/useVariableRegistry";
import { Badge, Button, Dialog, Field, Input, riskTone } from "../ui";
import { LoopBodyEditor } from "./LoopBodyEditor";
import { SchemaForm } from "./SchemaForm";
import type { DStep } from "../../types/designer";

export function StepEditDialog({
  open,
  step,
  meta,
  availableVars,
  onClose,
  onSave,
  onDelete,
}: {
  open: boolean;
  step: DStep | null;
  meta?: ActionMeta;
  availableVars: VariableInfo[];
  onClose: () => void;
  onSave: (next: DStep) => void;
  onDelete?: () => void;
}) {
  const [draft, setDraft] = useState<DStep | null>(null);

  // step 或 open 变化 → 重置 draft（prop 驱动的状态生命周期，第三部 2.5）
  useEffect(() => {
    setDraft(step ? { ...step } : null);
  }, [step, open]);

  const schema = useMemo(
    () => (meta?.params ?? null) as Parameters<typeof SchemaForm>[0]["schema"],
    [meta],
  );

  if (!draft) return <Dialog open={false} onClose={onClose}>{null}</Dialog>;

  const title = draft.action || (draft.type ? `[${draft.type}]` : "未命名步骤");

  function patch(partial: Partial<DStep>) {
    setDraft((prev) => (prev ? { ...prev, ...partial } : prev));
  }

  function setParam(key: string, value: unknown) {
    let params: Record<string, unknown> = {};
    try { params = JSON.parse(draft!.params_json || "{}"); } catch { /* 坏 JSON 重开 */ }
    params[key] = value;
    patch({ params_json: JSON.stringify(params, null, 2) });
  }

  function save() {
    onSave(draft!);
    onClose();
  }

  return (
    <Dialog open={open} onClose={onClose} width={620}>
      {/* 头部：动作身份 + 风险 */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-800 truncate">
            {title}
          </h2>
          {meta && <Badge tone={riskTone(meta.risk)}>{meta.risk}</Badge>}
          {meta?.idempotency && (
            <Badge tone="neutral">{meta.idempotency}</Badge>
          )}
        </div>
        {meta?.description && (
          <p className="mt-0.5 text-[11px] text-slate-400">{meta.description}</p>
        )}
      </div>

      {/* 主体：参数表单 + 步骤元字段 */}
      <div className="px-4 py-3 space-y-4 max-h-[60vh] overflow-y-auto">
        <section className="space-y-3">
          <SchemaForm
            schema={schema}
            values={safeParse(draft.params_json)}
            availableVars={availableVars}
            onChange={setParam}
          />
        </section>

        {draft.type === "foreach" && (
          <section className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-[11px] font-medium text-slate-600">
              循环体步骤（每轮迭代按序执行）
              <span className="ml-1 text-slate-300">
                可用变量: row(当前项) / index
              </span>
            </p>
            <LoopBodyEditor
              steps={draft.body_steps ?? []}
              onChange={(next) => patch({ body_steps: next })}
            />
          </section>
        )}

        <details className="group">
          <summary className="text-[11px] text-slate-400 cursor-pointer
                              select-none hover:text-slate-600">
            高级选项
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <Field label="步骤 ID"><Input value={draft.id}
              onChange={(e) => patch({ id: e.target.value })} /></Field>
            <Field label="输出变量" hint="output_as">
              <Input value={draft.output_as}
                onChange={(e) => patch({ output_as: e.target.value })} /></Field>
            <Field label="执行条件" hint="Python 表达式">
              <Input value={draft.condition} placeholder="steps.x.ok == true"
                onChange={(e) => patch({ condition: e.target.value })} /></Field>
            <Field label="失败跳转" hint="步骤 ID">
              <Input value={draft.on_failure_goto}
                onChange={(e) => patch({ on_failure_goto: e.target.value })} /></Field>
          </div>
        </details>
      </div>

      {/* 底部操作条 */}
      <div className="flex items-center px-4 py-2.5 border-t border-slate-100
                      bg-slate-50/50">
        {onDelete && (
          <Button variant="danger" size="sm" onClick={() => { onDelete(); onClose(); }}>
            <Trash2 size={12} /> 删除
          </Button>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
          <Button variant="primary" size="sm" onClick={save}>保存</Button>
        </div>
      </div>
    </Dialog>
  );
}

function safeParse(json: string): Record<string, unknown> {
  try { return JSON.parse(json || "{}") as Record<string, unknown>; }
  catch { return {}; }
}