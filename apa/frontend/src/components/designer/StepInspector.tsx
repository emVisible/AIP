/**
 * StepInspector —— 设计器右侧属性面板（影刀式，即改即存）。
 *
 * 单一职责：当前选中步骤的参数与元字段编辑。
 * 数据流：props.step 即真相源，每次编辑经 onChange(patch) 即时回写
 * DesignerPage 的 steps 状态（侧栏范式无「保存/取消」，所见即所得）。
 *
 * 参数表单优先走 SchemaForm（registry schema 驱动 + 变量引用）；
 * 无 schema 时（flow.* 内建节点 / 未定义 params）回退 JSON 直编。
 */
import { useEffect, useState } from "react";
import { Copy, Crosshair, Globe, Trash2, X } from "lucide-react";

import type { ActionMeta } from "../../api/types";
import type { VariableInfo } from "../../hooks/useVariableRegistry";
import { stepSub, stepTitle } from "../../lib/actionDisplay";
import { Badge, Button, Field, Input, riskTone } from "../ui";
import { LoopBodyEditor } from "./LoopBodyEditor";
import { SchemaForm } from "./SchemaForm";
import type { DStep } from "../../types/designer";

export function StepInspector({
  step,
  index,
  meta,
  availableVars,
  onChange,
  onDuplicate,
  onDelete,
  onClose,
  onPickFromScreen,
  onPickFromPage,
}: {
  step: DStep;
  index: number;
  meta?: ActionMeta;
  availableVars: VariableInfo[];
  onChange: (patch: Partial<DStep>) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onClose: () => void;
  /** 参数含 element 的动作可从屏幕拾取填充。 */
  onPickFromScreen?: () => void;
  /** 参数含 target 的动作可从浏览器页面选取填充。 */
  onPickFromPage?: () => void;
}) {
  const title = stepTitle(step) || "(未设置动作)";
  const sub = stepSub(step);
  const schema = (meta?.params ?? null) as
    | Parameters<typeof SchemaForm>[0]["schema"]
    | null;
  const pickable = !!schema?.properties?.element;
  const pagePickable = !pickable && !!schema?.properties?.target;

  function setParam(key: string, value: unknown) {
    let params: Record<string, unknown> = {};
    try { params = JSON.parse(step.params_json || "{}"); } catch { /* 坏 JSON */ }
    params[key] = value;
    onChange({ params_json: JSON.stringify(params, null, 2) });
  }

  return (
    <aside className="w-[320px] shrink-0 border-l border-slate-200 bg-white
                      flex flex-col overflow-hidden">
      {/* 头部：步骤身份 */}
      <header className="px-3 py-2.5 border-b border-slate-100">
        <div className="flex items-start gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5
                           mt-px shrink-0 rounded-full bg-zinc-900 text-white
                           text-[10px] font-semibold">
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-slate-800 truncate"
                title={title}>
              {title}
            </h2>
            {sub && (
              <p className="text-[10px] font-mono text-slate-400 truncate">
                {sub}
              </p>
            )}
            {(meta?.risk || meta?.idempotency) && (
              <div className="flex gap-1 mt-1">
                {meta?.risk && (
                  <Badge tone={riskTone(meta.risk)}>{meta.risk}</Badge>
                )}
                {meta?.idempotency && (
                  <Badge tone="neutral">{meta.idempotency}</Badge>
                )}
              </div>
            )}
          </div>
          <button onClick={onClose}
            className="shrink-0 p-1 rounded text-slate-300
                       hover:text-slate-600 hover:bg-slate-100"
            aria-label="关闭属性面板">
            <X size={14} />
          </button>
        </div>
        {meta?.description && (
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
            {meta.description}
          </p>
        )}
      </header>

      {/* 主体：参数 + 循环体 + 高级 */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        <section>
          <div className="flex items-center mb-2 gap-1">
            <p className="text-[10px] font-semibold text-slate-400
                          uppercase tracking-wide">参数</p>
            <div className="ml-auto flex gap-0.5">
              {pickable && onPickFromScreen && (
                <button onClick={onPickFromScreen}
                  title="启动桌面拾取，悬停目标元素后点「捕获」自动填入"
                  className="inline-flex items-center gap-1 px-1.5
                             h-5 rounded text-[10px] font-medium
                             text-violet-600 hover:bg-violet-50">
                  <Crosshair size={11} /> 从屏幕拾取
                </button>
              )}
              {pagePickable && onPickFromPage && (
                <button onClick={onPickFromPage}
                  title="打开拾取浏览器，点击页面元素自动生成选择器填入"
                  className="inline-flex items-center gap-1 px-1.5
                             h-5 rounded text-[10px] font-medium
                             text-sky-600 hover:bg-sky-50">
                  <Globe size={11} /> 从页面选取
                </button>
              )}
            </div>
          </div>
          {schema ? (
            <SchemaForm
              schema={schema}
              values={safeParse(step.params_json)}
              availableVars={availableVars}
              onChange={setParam}
            />
          ) : (
            <RawJsonEditor key={step.id} initial={step.params_json}
                           onCommit={(json) =>
                             onChange({ params_json: json })} />
          )}
        </section>

        {step.type === "foreach" && (
          <section className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-[11px] font-medium text-slate-600">
              循环体步骤（每轮迭代按序执行）
              <span className="ml-1 text-slate-300">
                可用变量: row(当前项) / index
              </span>
            </p>
            <LoopBodyEditor
              steps={step.body_steps ?? []}
              onChange={(next) => onChange({ body_steps: next })}
            />
          </section>
        )}

        <details className="group border-t border-slate-100 pt-3">
          <summary className="text-[11px] text-slate-400 cursor-pointer
                              select-none hover:text-slate-600">
            高级选项
          </summary>
          <div className="mt-2 space-y-2.5">
            <Field label="输出变量" hint="output_as">
              <Input value={step.output_as}
                onChange={(e) => onChange({ output_as: e.target.value })} />
            </Field>
            <Field label="执行条件" hint="Python 表达式">
              <Input value={step.condition} placeholder="steps.x.ok == true"
                onChange={(e) => onChange({ condition: e.target.value })} />
            </Field>
            <Field label="失败跳转" hint="步骤 ID">
              <Input value={step.on_failure_goto}
                onChange={(e) =>
                  onChange({ on_failure_goto: e.target.value })} />
            </Field>
            <Field label="步骤 ID">
              <Input value={step.id}
                onChange={(e) => onChange({ id: e.target.value })} />
            </Field>
          </div>
        </details>
      </div>

      {/* 底部操作条 */}
      <footer className="flex items-center gap-2 px-3 py-2 border-t
                         border-slate-100 bg-slate-50/60">
        <Button variant="secondary" size="sm" onClick={onDuplicate}>
          <Copy size={12} /> 复制
        </Button>
        <Button variant="danger" size="sm" onClick={onDelete}>
          <Trash2 size={12} /> 删除
        </Button>
      </footer>
    </aside>
  );
}

/** 无 schema 回退：JSON 直编（本地态允许输入中途非法，失焦提交）。 */
function RawJsonEditor({ initial, onCommit }: {
  initial: string;
  onCommit: (json: string) => void;
}) {
  const [text, setText] = useState(initial);
  const [bad, setBad] = useState(false);

  // 外部重置（切换步骤由 key 重挂载处理；同步骤外部改写时跟随）
  useEffect(() => { setText(initial); }, [initial]);

  function commit() {
    if (!text.trim()) { setBad(false); return; }
    try {
      const parsed: unknown = JSON.parse(text);
      setBad(false);
      onCommit(JSON.stringify(parsed, null, 2));
    } catch {
      setBad(true);
    }
  }

  return (
    <div className="space-y-1">
      <textarea
        className={`w-full px-2.5 py-2 text-[11px] font-mono border rounded-md
                    resize-y min-h-[96px] leading-relaxed outline-none
                    focus:ring-2 ${bad
          ? "border-red-300 focus:ring-red-500/20"
          : "border-slate-200 focus:ring-blue-500/20 focus:border-slate-400"}`}
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit} />
      <p className="text-[10px] text-slate-300">
        {bad
          ? <span className="text-red-400">JSON 格式错误，修正后自动保存</span>
          : "该动作未提供参数定义，可直接编辑 JSON"}
      </p>
    </div>
  );
}

function safeParse(json: string): Record<string, unknown> {
  try { return JSON.parse(json || "{}") as Record<string, unknown>; }
  catch { return {}; }
}
