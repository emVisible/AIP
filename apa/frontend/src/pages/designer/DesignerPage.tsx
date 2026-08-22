/**
 * APA 低代码流程设计器（§10.2 模式 B 可视化编辑）。
 *
 * 三面板布局：动作目录（左）· React Flow 画布（中）· 属性+试运行（右）。
 * 步骤数组为逻辑执行顺序；画布位置仅视觉布局，不影响执行序。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  type Node,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";

import { api } from "../../api/client";
import type { ProcessInfo } from "../../api/types";

interface DStep {
  id: string;
  type: string;
  action: string;
  target: string;
  params_json: string;
  condition: string;
  output_as: string;
  on_failure_goto: string;
}

interface ProcessMeta {
  id: string;
  trigger_name: string;
  max_actions: number;
}

function blankStep(i: number): DStep {
  return {
    id: `step_${i + 1}`, type: "", action: "", target: "",
    params_json: "{}", condition: "", output_as: "",
    on_failure_goto: "",
  };
}

type StepNodeData = { label: string; sub?: string; tone: string };

function StepNodeView({ data }: { data: StepNodeData }) {
  return (
    <div className={`rounded-lg border-2 px-3 py-2 min-w-[140px]
                     shadow-sm bg-white ${data.tone}`}>
      <p className="text-xs font-semibold text-slate-700 truncate">
        {data.label}
      </p>
      {data.sub && (
        <p className="text-[10px] text-slate-400 mt-0.5 truncate">{data.sub}</p>
      )}
    </div>
  );
}

const nodeTypes = { step: StepNodeView };

export function DesignerPage() {
  // ---- 状态 ----
  const [meta, setMeta] = useState<ProcessMeta>({
    id: "", trigger_name: "", max_actions: 50 });
  const [steps, setSteps] = useState<DStep[]>([blankStep(0)]);
  const [yamlText, setYamlText] = useState("");
  const [statusMsg, setStatusMsg] = useState("就绪");
  const [processList, setProcessList] = useState<ProcessInfo[]>([]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // ---- steps → RF 同步 ----
  const syncGraph = useCallback(() => {
    const nodes: Node[] = steps.map((s, i) => ({
      id: s.id || `n${i}`,
      type: "step" as const,
      position: { x: 200, y: i * 100 },
      data: {
        label: s.id || `step_${i + 1}`,
        sub: s.action || s.type || "",
        tone: s.condition ? "border-amber-300" : "border-slate-300",
      } satisfies StepNodeData,
    }));
    const edges: Edge[] = [];
    for (let i = 0; i < steps.length - 1; i++) {
      edges.push({
        id: `e${i}`,
        source: steps[i]!.id || `n${i}`,
        target: steps[i + 1]!.id || `n${i + 1}`,
        animated: Boolean(steps[i]!.condition),
      });
    }
    setRfNodes(nodes);
    setRfEdges(edges);
  }, [steps, setRfNodes, setRfEdges]);

  useEffect(() => { syncGraph(); }, [syncGraph]);

  // ---- 步骤 CRUD ----
  const updateStep = useCallback(
    (i: number, patch: Partial<DStep>) =>
      setSteps(prev => prev.map(
        (s, j) => (j === i ? { ...s, ...patch } : s))),
    [],
  );

  const addStep = useCallback(
    () => setSteps(prev => [...prev, blankStep(prev.length)]),
    [],
  );

  const removeStep = useCallback(
    (i: number) => setSteps(prev => prev.filter((_, j) => j !== i)),
    [],
  );

  const moveStep = useCallback(
    (i: number, dir: -1 | 1) =>
      setSteps(prev => {
        const next = [...prev];
        const j = i + dir;
        if (j < 0 || j >= next.length) return prev;
        const tmp = next[i]!;
        next[i] = next[j]!;
        next[j] = tmp;
        return next;
      }),
    [],
  );

  // ---- YAML 双向 ----
  function buildForm() {
    return {
      id: meta.id,
      trigger_name: meta.trigger_name,
      max_actions: meta.max_actions,
      steps: steps.map(s => {
        let parsed: Record<string, unknown> = {};
        try { parsed = JSON.parse(s.params_json || "{}"); } catch {}
        return { ...s, params_json: undefined, params: parsed };
      }),
      error_handlers: [] as Record<string, unknown>[],
    };
  }

  async function syncToYaml() {
    try {
      const d = await api<{ yaml: string }>("/api/processes/from-form", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ form: buildForm() }),
      });
      setYamlText(d.yaml);
      setStatusMsg("已同步 YAML ✓");
    } catch (e) {
      setStatusMsg(`同步失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function loadFromYaml() {
    try {
      interface FormResponse {
        form: { id: string; trigger_name: string;
                max_actions: number; steps: DStep[] };
      }
      const d = await api<FormResponse>(
        "/api/processes/to-form",
        { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml: yamlText }) });
      setMeta({
        id: d.form.id, trigger_name: d.form.trigger_name,
        max_actions: d.form.max_actions,
      });
      setSteps(d.form.steps.map(s => ({
        ...s, params_json:
          typeof s.params_json === "string"
            ? s.params_json : "{}",
      })));
      setStatusMsg("已从 YAML 加载表单 ✓");
    } catch (e) {
      setStatusMsg(`解析失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function save() {
    try {
      const form = buildForm();
      const yd = await api<{ yaml: string }>(
        "/api/processes/from-form",
        { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ form }) });
      await api("/api/processes/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: meta.id || "untitled", yaml: yd.yaml }),
      });
      setStatusMsg(`已保存 ${meta.id} ✓`);
      void refreshProcessList();
    } catch (e) {
      setStatusMsg(`保存失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function openFile(fileId: string) {
    try {
      const d = await api<{ yaml: string }>(`/api/processes/get/${fileId}`);
      setYamlText(d.yaml);
      await loadFromYaml();
      setMeta(m => ({ ...m, id: fileId }));
      setStatusMsg(`已加载 ${fileId} ✓`);
    } catch (e) {
      setStatusMsg(`加载失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function refreshProcessList() {
    try {
      setProcessList(await api<ProcessInfo[]>("/api/designer/list"));
    } catch { /* ignore */ }
  }
  useEffect(() => { void refreshProcessList(); }, []);

  // ---- 渲染 ----
  const stepRows = steps.map((s, i) => (
    <div key={s.id || i}
      className="flex gap-2 items-end flex-wrap border border-slate-100
                 rounded-lg px-2 py-1.5 bg-slate-50 text-xs">
      <div className="w-24">
        <label className="text-[10px] text-slate-300">ID</label>
        <input className="w-full px-1 py-0.5 text-xs border rounded"
          value={s.id}
          onChange={e => updateStep(i, { id: e.target.value })}/>
      </div>
      <div className="flex-[2]">
        <label className="text-[10px] text-slate-300">action</label>
        <input className="w-full px-1 py-0.5 text-xs border rounded"
          value={s.action}
          onChange={e => updateStep(i, { action: e.target.value })}/>
      </div>
      <div className="flex-[2]">
        <label className="text-[10px] text-slate-300">condition</label>
        <input className="w-full px-1 py-0.5 text-xs border rounded"
          value={s.condition}
          onChange={e => updateStep(i, { condition: e.target.value })}/>
      </div>
      <button onClick={() => moveStep(i, -1)} title="上移">↑</button>
      <button onClick={() => moveStep(i, 1)} title="下移">↓</button>
      <button onClick={() => removeStep(i)}
        className="text-red-400 hover:text-red-600 px-1">✕</button>
    </div>
  ));

  const processItems = processList.map(p => (
    <div key={p.id}
         className="flex items-center justify-between px-2 py-1 text-xs
                    hover:bg-slate-50 rounded cursor-pointer"
         onClick={() => void openFile(p.id)}>
      <span>{p.id}</span>
      <span className={p.valid ? "text-emerald-500" : "text-red-400"}>
        {p.valid ? `${p.steps} 步骤` : p.error}
      </span>
    </div>
  ));

  return (
    <div className="space-y-4">
      {/* 元信息 */}
      <div className="flex gap-3 items-end flex-wrap">
        <div>
          <label className="text-[11px] text-slate-400">流程 ID</label>
          <input className="w-48 px-2 py-1 text-sm border rounded"
            value={meta.id}
            onChange={e => setMeta(m => ({ ...m, id: e.target.value }))}/>
        </div>
        <div>
          <label className="text-[11px] text-slate-400">触发事件</label>
          <input className="w-64 px-2 py-1 text-sm border rounded"
            value={meta.trigger_name}
            onChange={e => setMeta(m => ({ ...m, trigger_name: e.target.value }))}/>
        </div>
        <div>
          <label className="text-[11px] text-slate-400">max_actions</label>
          <input className="w-20 px-2 py-1 text-sm border rounded" type="number"
            value={meta.max_actions}
            onChange={e => setMeta(m => ({ ...m, maxActions: +e.target.value || 50}))}/>
        </div>
        <button onClick={() => void save()}
          className="ml-auto px-4 py-1.5 text-sm font-semibold text-white
                     bg-brand rounded-lg hover:bg-blue-700 transition-colors">
          💾 保存
        </button>
      </div>

      {/* 三面板 */}
      <div className="grid grid-cols-[240px_1fr_280px] gap-3 items-start">

        {/* 动作目录 */}
        <CatalogPanel />

        {/* React Flow 画布 */}
        <div className="space-y-2 min-w-0">
          <div style={{ height: 420 }}
               className="border border-slate-200 rounded-xl overflow-hidden">
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes}
              fitView
            >
              <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
              <Controls />
            </ReactFlow>
          </div>

          {/* 步骤卡片列表 */}
          {stepRows}
          <button onClick={addStep}
            className="px-3 py-1 text-xs border border-dashed border-slate-300
                       rounded-lg text-slate-500 hover:border-brand hover:text-brand
                       transition-colors">
            ＋ 添加步骤
          </button>

          {/* YAML 编辑区 */}
          <details className="mt-2">
            <summary className="text-xs text-slate-400 cursor-pointer">
              YAML 预览 / 手动编辑</summary>
            <textarea
              className="w-full mt-1 p-3 text-xs font-mono border rounded
                         resize-y min-h-[200px]"
              rows={14}
              value={yamlText}
              onChange={e => setYamlText(e.target.value)} />
            <button onClick={() => void syncToYaml()} className="mr-1">YAML ← 表单</button>
            <button onClick={() => void loadFromYaml()}
              className="mt-1 px-3 py-1 text-xs border rounded hover:bg-slate-50">
              YAML → 表单
            </button>
          </details>
        </div>

        {/* 属性面板 */}
        <div className="space-y-4">
          <TestRunPanelLazy />
        </div>
      </div>

      <p className="text-xs text-slate-500">{statusMsg}</p>

      {/* 已保存流程列表 */}
      <details className="mt-2">
        <summary className="text-xs text-slate-400 cursor-pointer">
          已保存流程 ({processList.filter(p => p.valid).length})</summary>
        <div className="mt-1 space-y-1">{processItems}</div>
      </details>
    </div>
  );

  // --- 内部辅助 ---
  function TestRunPanelLazy() {
    return (
      <div className="space-y-2 p-1">
        <p className="text-[10px] font-semibold text-slate-400 uppercase">
          沙盒试运行</p>
        <p className="text-xs text-slate-400 p-2">
          试运行由 M-B 后续迭代提供完整 UI；当前通过 CLI 触发</p>
        <button onClick={() => void syncToYaml()}
          className="px-3 py-1 text-xs border rounded hover:bg-slate-50">
          同步 YAML
        </button>
      </div>
    );
  }

  function CatalogPanel() {
    return (
      <div className="space-y-1">
        <p className="text-[10px] font-semibold text-slate-400 uppercase">动作目录</p>
        <input className="w-full px-2 py-1 text-xs border rounded"
               placeholder="搜索动作…" />
        <p className="text-xs text-slate-400 p-2">
          完整动作目录需接入 /api/registry/actions（M-B 后续迭代）</p>
      </div>
    );
  }
}