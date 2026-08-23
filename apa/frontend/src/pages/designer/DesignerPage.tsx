/**
 * APA 低代码流程设计器 — Activity Pipeline Editor。
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
import type { ActionMeta, ProcessInfo } from "../../api/types";
import { CatalogPanel } from "../../components/designer/CatalogPanel";
import { ParamsPanel } from "../../components/designer/ParamsPanel";
import { TestRunPanel } from "../../components/designer/TestRunPanel";
import { SpyPanel } from "../../components/designer/SpyPanel";
import "../../types/desktop";

/** 模板信息（/api/templates 返回结构）。 */
interface TemplateInfo { id: string; name: string; description: string; yaml: string }

/** 录制会话状态（DesignerPage 内联模态使用）。 */
interface RecordingState {
  sid: string;
  url: string;
  events: number;
  phase: "enter" | "running";
}

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

function blankStep(i: number): DStep {
  return {
    id: `step_${i + 1}`, type: "", action: "", target: "",
    params_json: "{}", condition: "", output_as: "",
    on_failure_goto: "",
  };
}

/** 按目录选择生成带模板参数的步骤（流程控制节点预填骨架）。 */
function stepFromAction(action: string, i: number): DStep {
  const base = blankStep(i);
  if (action === "flow.foreach") {
    return { ...base, type: "foreach", id: `loop_${i + 1}`,
      params_json: JSON.stringify({
        source: "{{steps.extract_table.rows}}", item_var: "row",
        body_action: "", body_params: {},
      }, null, 2) };
  }
  if (action === "flow.sub_process") {
    return { ...base, type: "sub_process", id: `sub_${i + 1}`,
      params_json: JSON.stringify({
        process_id: "", input: {},
      }, null, 2) };
  }
  if (action === "flow.ai_decision") {
    return { ...base, type: "ai_decision", id: `decision_${i + 1}`,
      params_json: JSON.stringify({
        context: [], available_actions: [],
      }, null, 2) };
  }
  return { ...base, action };
}

type StepNodeData = { label: string; sub?: string; tone: string };

function StepNodeView({ data }: { data: StepNodeData }) {
  return (
    <div className={`rounded-lg border-2 px-3 py-2 min-w-[150px] shadow-sm bg-white ${data.tone}`}>
      <p className="text-xs font-semibold text-slate-700 truncate">{data.label}</p>
      {data.sub && (
        <p className="text-[10px] text-slate-400 mt-0.5 truncate">{data.sub}</p>
      )}
    </div>
  );
}

const nodeTypes = { step: StepNodeView };

export function DesignerPage() {
  const [metaId, setMetaId] = useState("");
  const [triggerName, setTriggerName] = useState("");
  const [maxActions, setMaxActions] = useState(50);
  const [steps, setSteps] = useState<DStep[]>([blankStep(0)]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [statusMsg, setStatusMsg] = useState("就绪");
  const [processList, setProcessList] = useState<ProcessInfo[]>([]);
  const [catalog, setCatalog] = useState<Record<string, ActionMeta>>({});
  const [currentFile, setCurrentFile] = useState("");
  const [recording, setRecording] = useState<RecordingState | null>(null);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // steps → RF graph sync
  useEffect(() => {
    const nodes: Node[] = steps.map((s, i) => ({
      id: s.id || `n${i}`,
      type: "step" as const,
      position: { x: 200, y: i * 100 },
      data: {
        label: s.id || `step_${i + 1}`,
        sub: s.action || s.type || "\u2014",
        tone: selectedIdx === i
          ? "border-blue-500 ring-2 ring-blue-200"
          : s.condition
            ? "border-amber-300"
            : "border-slate-300",
      } satisfies StepNodeData,
    }));
    const edges: Edge[] = [];
    for (let i = 0; i < steps.length - 1; i++) {
      edges.push({
        id: `e${i}`,
        source: steps[i]?.id ?? `n${i}`,
        target: steps[i + 1]?.id ?? `n${i + 1}`,
        animated: true,
      });
    }
    setRfNodes(nodes);
    setRfEdges(edges);
  }, [steps, selectedIdx, setRfNodes, setRfEdges]);

  // 数据加载
  useEffect(() => {
    api<ProcessInfo[]>("/api/processes").then(setProcessList).catch(() => {});
    api<Record<string, ActionMeta>>("/api/registry/actions")
      .then(setCatalog)
      .catch(() => {});
  }, []);

  const updateStep = useCallback(
    (i: number, patch: Partial<DStep>) =>
      setSteps(prev => prev.map((s, j) => (j === i ? { ...s, ...patch } : s))),
    [],
  );

  function buildForm() {
    return {
      id: metaId,
      trigger_name: triggerName,
      max_actions: maxActions,
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
      const form = buildForm();
      const d = await api<{ yaml: string }>("/api/processes/from-form", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ form }),
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
      const d = await api<FormResponse>("/api/processes/to-form", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: yamlText }),
      });
      setMetaId(d.form.id);
      setTriggerName(d.form.trigger_name);
      setMaxActions(d.form.max_actions);
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
      await post("/api/processes/save", {
        id: metaId || "untitled", yaml: yamlText || "{}",
      });
      setStatusMsg(`已保存 ${metaId} ✓`);
      void refreshProcessList();
    } catch (e) {
      setStatusMsg(`保存失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  function refreshProcessList() {
    api<ProcessInfo[]>("/api/processes").then(setProcessList).catch(() => {});
  }

  async function importTemplate(t: TemplateInfo) {
    try {
      setYamlText(t.yaml);
      await loadFromYaml();
      setMetaId(`${t.id}_${Date.now().toString(36).slice(-4)}`);
      setCurrentFile("");
      setStatusMsg(`已从模板导入 ${t.name} ✓（记得另存）`);
    } catch (e) {
      setStatusMsg(`模板导入失败: ${e instanceof Error ? e.message : e}`);
    }
  }


  function captureSpyElement(el: {
    role: string; title: string; app_name: string;
    bounds: { x: number; y: number; w: number; h: number } | null;
    ax_path: unknown[];
  }) {
    setSteps(prev => {
      const step: DStep = {
        id: `spy_${prev.length + 1}`,
        type: "", action: "desktop.ui.click_element",
        target: "", condition: "", output_as: "",
        on_failure_goto: "",
        params_json: JSON.stringify({ element: el }, null, 2),
      };
      setSelectedIdx(prev.length);
      return [...prev, step];
    });
    setStatusMsg(`已捕获 ${el.app_name} · ${el.role}` +
      (el.title ? ` "${el.title.slice(0, 24)}"` : "") +
      " → 插入 click_element 步骤");
  }

  // ---- 浏览器录制 ----------------------------------------------------------
  function startRecording() {
    if (!recording || !recording.url.startsWith("http")) return;
    post("/api/recorder/start", { url: recording.url })
      .then((r: { session_id?: string; detail?: string }) => {
        if (!r.session_id) throw new Error(r.detail ?? "启动失败");
        setRecording({ url: recording.url, events: 0,
                       sid: r.session_id, phase: "running" });
        setStatusMsg("录制中：在打开的浏览器里操作…");
      })
      .catch((e: unknown) => setStatusMsg(
        `录制启动失败: ${e instanceof Error ? e.message : e}`));
  }

  function pollRecording(sid: string) {
    api<{ events: number; active: boolean; error: string | null }>(
      `/api/recorder/status/${sid}`)
      .then(st => setRecording(prev => prev
        ? { ...prev, events: st.events }
        : prev))
      .catch(() => {});
  }

  const recSid = recording?.phase === "running" ? recording.sid : null;
  useEffect(() => {
    if (!recSid) return;
    const t = setInterval(() => pollRecording(recSid), 1500);
    return () => clearInterval(t);
  }, [recSid]);

  function stopRecording() {
    if (!recording) return;
    post(`/api/recorder/stop/${recording.sid}`,
         { process_id: "recorded_flow" })
      .then(async (r: { yaml?: string; steps?: number }) => {
        setRecording(null);
        if (r.yaml) {
          setYamlText(r.yaml);
          await loadFromYaml();
          setStatusMsg(`录制完成：${r.steps} 个步骤已导入画布 ✓`);
        } else {
          setStatusMsg("录制结束，但未捕获到任何操作");
        }
      })
      .catch((e: unknown) => {
        setRecording(null);
        setStatusMsg(`停止录制失败: ${e instanceof Error ? e.message : e}`);
      });
  }

  async function openFile(fileId: string) {
    try {
      const d = await api<{ yaml: string }>(`/api/processes/get/${fileId}`);
      setYamlText(d.yaml);
      await loadFromYaml();
      setMetaId(fileId);
      setCurrentFile(fileId);
      setStatusMsg(`已加载 ${fileId} ✓`);
    } catch (e) {
      setStatusMsg(`加载失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 工具栏 */}
      <div className="flex items-center gap-3 px-4 py-2 border-b bg-white shadow-sm z-10">
        <input className="w-48 px-2 py-1 text-sm border rounded-md outline-none"
          placeholder="流程 ID…" value={metaId}
          onChange={e => setMetaId(e.target.value)} />
        <input className="w-72 px-2 py-1 text-sm border rounded-md"
          placeholder="触发事件…"
          value={triggerName} onChange={e => setTriggerName(e.target.value)} />
        <input className="w-20 px-2 py-1 text-sm border rounded" type="number"
          value={maxActions}
          onChange={e => setMaxActions(+e.target.value || 50)} />
        <button
          className="ml-auto px-4 py-1.5 text-xs font-semibold text-white bg-violet-600 rounded-md hover:bg-violet-700 transition-colors"
          onClick={() => setRecording({ sid: "", url: "https://",
                                        events: 0, phase: "enter" })}>
          🎙 录制
        </button>
        <button
          className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
          onClick={() => void save()}>
          💾 保存
        </button>
      </div>

      {/* 三面板 */}
      <div className="flex-1 grid grid-cols-[220px_1fr_260px] overflow-hidden">

        {/* 左：动作目录 */}
        <div className="border-r p-3 overflow-y-auto bg-white">
          <CatalogPanel onInsert={(action: string) => {
            setSteps(prev => [...prev, stepFromAction(action, prev.length)]);
          }} />
        </div>

        {/* 中：画布 + 步骤编辑 */}
        <div className="overflow-y-auto p-3">
          <div style={{ height: Math.max(280, rfNodes.length * 80 + 60) }}
               className="border rounded-xl min-h-[250px] overflow-hidden">
            <ReactFlow
              nodes={rfNodes} edges={rfEdges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes} fitView
            >
              <Background variant={BackgroundVariant.Dots}
                          gap={20} size={1.5} color="#cbd5e1" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>

          <div className="mt-3 space-y-2">
            {steps.map((s, i) => (
              <div key={s.id || i} onClick={() => setSelectedIdx(i)}
                className={`cursor-pointer rounded-lg border px-3 py-2 text-xs ${
                  selectedIdx === i
                    ? "ring-1 ring-blue-300 border-blue-300 bg-blue-50"
                    : "border-slate-200 bg-white"}`}>
                <span className="font-semibold mr-2">{i + 1}. {s.id}</span>
                <span className="text-slate-400 font-mono">
                  {s.action || (s.type ? `[${s.type}]` : "(未设置)")}
                </span>
              </div>
            ))}
          </div>

          <button onClick={() =>
            setSteps(prev => [...prev, blankStep(prev.length)])}
            className="w-full mt-2 py-2 text-xs border border-dashed border-slate-300
                       rounded-lg text-slate-400 hover:border-blue-400 transition-colors">
            ＋ 添加步骤
          </button>

          {/* YAML 编辑区 */}
          <details className="mt-4">
            <summary className="text-xs text-slate-400 cursor-pointer">YAML</summary>
            <textarea className="w-full mt-1 p-2 text-xs font-mono border rounded resize-y min-h-[120px]"
              rows={10} value={yamlText} onChange={e => setYamlText(e.target.value)} />
            <div className="flex gap-2 mt-1">
              <button onClick={() => void syncToYaml()}
                className="px-3 py-1 text-xs border rounded hover:bg-slate-50">
                表单 → YAML
              </button>
              <button onClick={() => void loadFromYaml()}
                className="px-3 py-1 text-xs border rounded hover:bg-slate-50">
                YAML → 表单
              </button>
            </div>
          </details>
        </div>

        {/* 右：属性面板 + 试运行 */}
        <div className="border-l p-3 space-y-3 overflow-y-auto bg-white">
          <p className="text-xs font-semibold">属性面板</p>
          <ParamsPanel
            steps={steps} selectedIdx={selectedIdx}
            onUpdate={updateStep} catalog={catalog}
          />
          {selectedIdx != null && steps[selectedIdx] && (
            <div className="space-y-2 text-xs">
              <div>
                <label className="text-slate-400">ID</label>
                <input className="w-full px-2 py-1 border rounded mt-0.5"
                  value={steps[selectedIdx]?.id ?? ""}
                  onChange={e => setSteps(prev =>
                    prev.map((s, j) => j === selectedIdx
                      ? { ...s, id: e.target.value } : s))} />
              </div>
              <div>
                <label className="text-slate-400">动作名</label>
                <input className="w-full px-2 py-1 border rounded mt-0.5"
                  value={steps[selectedIdx]?.action ?? ""}
                  onChange={e => setSteps(prev =>
                    prev.map((s, j) => j === selectedIdx
                      ? { ...s, action: e.target.value } : s))} />
              </div>
              <div>
                <label className="text-slate-400">参数 (JSON)</label>
                <textarea className="w-full px-2 py-1 border rounded mt-0.5 font-mono"
                  rows={4} value={steps[selectedIdx]?.params_json ?? "{}"}
                  onChange={e => setSteps(prev =>
                    prev.map((s, j) => j === selectedIdx
                      ? { ...s, params_json: e.target.value } : s))} />
              </div>
            </div>
          )}
          {selectedIdx == null && (
            <p className="text-xs text-slate-400 pt-2">点击画布中的节点以编辑属性</p>
          )}

          <TestRunPanel yaml={yamlText} />

          <SpyPanel onCapture={captureSpyElement} />

          {/* 模板库 */}
          <TemplateLibrary onPick={importTemplate} />

          {/* 已保存流程列表 */}
          <details className="mt-3">
            <summary className="text-xs text-slate-400 cursor-pointer">
              已保存流程 ({processList.filter(p => p.valid).length})
            </summary>
            <div className="mt-1 space-y-0.5">
              {processList.map(p => (
                <div key={p.id}
                     onClick={() => void openFile(p.id)}
                     className="flex items-center justify-between px-2 py-1 text-xs
                                hover:bg-slate-50 rounded cursor-pointer">
                  <span className="font-mono">{p.id}</span>
                  <span className={p.valid ? "text-emerald-500" : "text-red-400"}>
                    {p.valid ? `${p.steps} 步骤` : "\u26a0"}
                  </span>
                </div>
              ))}
              {!processList.length && (
                <p className="text-xs text-slate-300">（暂无）</p>
              )}
            </div>
          </details>
        </div>
      </div>

      {/* 状态栏 */}
      <div className="px-4 py-1 bg-slate-900 text-slate-300 text-xs flex justify-between">
        <span>{statusMsg}</span>
        <span>{currentFile}</span>
      </div>

      {/* 录制模态 */}
      {recording && (
        <div className="fixed inset-0 bg-black/40 flex items-center
                        justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-5 w-[380px]">
            <p className="text-sm font-semibold mb-3">
              🎙 浏览器操作录制
            </p>
            {recording.phase === "enter" ? (
              <>
                <input autoFocus
                  className="w-full px-3 py-2 text-sm border rounded-md mb-3"
                  placeholder="起始 URL（https://…）"
                  value={recording.url}
                  onChange={e => setRecording({ ...recording,
                                                url: e.target.value })}
                  onKeyDown={e => {
                    if (e.key === "Enter") startRecording();
                  }} />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setRecording(null)}
                    className="px-3 py-1.5 text-xs border rounded-md
                               hover:bg-slate-50">取消</button>
                  <button onClick={startRecording}
                    className="px-4 py-1.5 text-xs font-semibold text-white
                               bg-violet-600 rounded-md hover:bg-violet-700">
                    开始录制
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-xs text-slate-500 mb-1">
                  {recording.url}
                </p>
                <p className="text-2xl font-bold text-violet-700 mb-3">
                  已捕获 {recording.events} 个事件
                  <span className="ml-2 inline-block w-2 h-2 rounded-full
                                   bg-red-500 animate-pulse align-middle" />
                </p>
                <p className="text-xs text-slate-400 mb-4">
                  在打开的浏览器窗口中点击/输入；完成后点「停止并导入」。
                </p>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setRecording(null)}
                    className="px-3 py-1.5 text-xs border rounded-md
                               hover:bg-slate-50">后台运行</button>
                  <button onClick={stopRecording}
                    className="px-4 py-1.5 text-xs font-semibold text-white
                               bg-red-600 rounded-md hover:bg-red-700">
                    ■ 停止并导入
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function post(path: string, json: unknown) {
  return fetch(`/api${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(json),
  }).then(r => r.json());
}

/** 模板库侧栏：从 /api/templates 拉取，点击导入画布。 */
function TemplateLibrary({ onPick }: { onPick: (t: TemplateInfo) => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TemplateInfo[]>([]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !items.length) {
      api<{ templates: TemplateInfo[] }>("/api/templates")
        .then(d => setItems(d.templates ?? []))
        .catch(() => {});
    }
  }

  return (
    <details className="mt-3" open={open} onToggle={(e) => {
      if ((e.target as HTMLDetailsElement).open !== open) toggle();
    }}>
      <summary className="text-xs text-slate-400 cursor-pointer">模板库</summary>
      <div className="mt-1 space-y-0.5">
        {items.map(t => (
          <div key={t.id}
               onClick={() => void onPick(t)}
               className="px-2 py-1 text-xs hover:bg-violet-50 rounded
                          cursor-pointer text-violet-700">
            📋 {t.name}
          </div>
        ))}
        {!items.length && (
          <p className="text-xs text-slate-300">（加载中…）</p>
        )}
      </div>
    </details>
  );
}
