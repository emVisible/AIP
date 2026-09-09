/**
 * APA 低代码流程设计器 — 三栏 IDE 布局（H1–H5 全特性终态）。
 *
 * 布局：左栏动作库（目录/拾取/网页/抓取）· 中央双视图（流程图主编辑面 /
 * 步骤列表）· 右侧属性面板。数据流：steps[] 是唯一真相源 → 同步生成
 * React Flow 节点链；画布节点位置仅视觉。
 *
 * 集成：桌面拾取（useDesktopSpy）· 网页拾取（扩展回传 + 抓取步骤生成）·
 * 计划态溯源（保存/试运行携带草稿凭证）· Studio 事件 ticker（H3 下行）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Edge,
  type Node,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import { AlignVerticalSpaceAround, Code2, Copy, FolderOpen,
         ListTree, Maximize, PanelLeftClose, PanelLeftOpen, Plus,
         Save, SquareDot, Terminal, Trash2, Workflow } from "lucide-react";

import { readDnDAction, readDnDStepIndex } from "./designerDnd";
import { generateDefaults } from "../../lib/schema-defaults";
import { actionSub, stepTitle } from "../../lib/actionDisplay";
import { nodeTypes, type StepNodeData }
  from "../../components/designer/StepNode";
import { EngineChip } from "../../components/designer/EngineChip";

import { api, post } from "../../api/client";
import { studioRpc } from "../../api/studio";
import type { ActionMeta, ProcessInfo } from "../../api/types";
import { CatalogPanel } from "../../components/designer/CatalogPanel";
import { StepInspector } from "../../components/designer/StepInspector";
import { BrowserPickPanel,
         type PickPayload, type ScrapeSpec }
  from "../../components/designer/BrowserPickPanel";
import { TestRunPanel } from "../../components/designer/TestRunPanel";
import { SpyPanel } from "../../components/designer/SpyPanel";
import { ScrapePanel } from "../../components/designer/ScrapePanel";
import { Badge, Button, Drawer, IconButton } from "../../components/ui";
import { availableVariables } from "../../hooks/useVariableRegistry";
import { useActionCatalog } from "../../hooks/useActionCatalog";
import { useDesktopSpy, type CapturedElement }
  from "../../hooks/useDesktopSpy";
import { useStudioEvents } from "../../hooks/useStudioEvents";
import type { DStep } from "../../types/designer";
import "../../types/desktop";

/** 模板信息（/api/templates 返回结构）。 */
interface TemplateInfo {
  id: string; name: string; description: string; yaml: string;
}

/** 录制会话状态（DesignerPage 内联模态使用）。 */
interface RecordingState {
  sid: string;
  url: string;
  events: number;
  phase: "enter" | "running";
}

function blankStep(i: number): DStep {
  return {
    id: `step_${i + 1}`, type: "", action: "", target: "",
    params_json: "{}", condition: "", output_as: "",
    on_failure_goto: "",
  };
}

/** 按目录选择生成带模板参数的步骤（流程控制节点预填骨架）。 */
function stepFromAction(action: string, i: number,
                        catalog?: Record<string, ActionMeta>): DStep {
  const base = blankStep(i);
  const meta = catalog?.[action];
  const defaults = generateDefaults(
    (meta?.params ?? null) as Parameters<typeof generateDefaults>[0]);
  const paramsJson = Object.keys(defaults).length
    ? JSON.stringify(defaults, null, 2)
    : "{}";

  if (action === "flow.foreach") {
    return { ...base, type: "foreach", id: `loop_${i + 1}`,
      params_json: JSON.stringify({
        source: "{{steps.extract_table.rows}}", item_var: "row",
        body_action: "", body_params: {},
      }, null, 2) };
  }
  if (action === "flow.sub_process") {
    return { ...base, type: "sub_process", id: `sub_${i + 1}`,
      params_json: JSON.stringify({ process_id: "", input: {} }, null, 2) };
  }
  if (action === "flow.ai_decision") {
    return { ...base, type: "ai_decision", id: `decision_${i + 1}`,
      params_json: JSON.stringify({ context: [], available_actions: [] },
                                   null, 2) };
  }
  return { ...base, action, params_json: paramsJson };
}

/** 参数摘要：取前两个标量参数渲染 k=v（列表卡与画布节点共用）。 */
function paramSummary(paramsJson: string): string {
  try {
    const p = JSON.parse(paramsJson || "{}") as Record<string, unknown>;
    const parts: string[] = [];
    for (const [k, v] of Object.entries(p)) {
      if (v == null || v === "" || typeof v === "object") continue;
      parts.push(`${k}=${String(v).slice(0, 24)}`);
      if (parts.length >= 2) break;
    }
    return parts.join(" · ");
  } catch { return ""; }
}

export function DesignerPage() {
  return (
    <ReactFlowProvider>
      <DesignerInner />
    </ReactFlowProvider>
  );
}

/** 内层：需要 useReactFlow 上下文。 */
function DesignerInner() {
  const [metaId, setMetaId] = useState("");
  const [triggerName, setTriggerName] = useState("");
  const [maxActions, setMaxActions] = useState(50);
  const [steps, setSteps] = useState<DStep[]>([blankStep(0)]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  /** 选中的失败跳转边 id（goto-*）；Delete 键删除它=清空源步骤字段。 */
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [statusMsg, setStatusMsg] = useState("就绪");
  const [processList, setProcessList] = useState<ProcessInfo[]>([]);
  // 动作目录走共享 hook（带重试，避免启动竞态下 catalog 永久为空）
  const { catalog } = useActionCatalog();
  const [currentFile, setCurrentFile] = useState("");
  const [recording, setRecording] = useState<RecordingState | null>(null);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition, fitView, setCenter, getZoom } = useReactFlow();

  /** 步骤卡右键菜单状态。 */
  const [menu, setMenu] = useState<{ idx: number; x: number; y: number }
                                 | null>(null);
  /** 排序拖拽悬停的目标卡下标（插入位置指示）。 */
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);
  /** 试运行 / YAML 底部抽屉。 */
  const [runOpen, setRunOpen] = useState(false);
  const [yamlOpen, setYamlOpen] = useState(false);
  /** 左栏工具面板 Tab。 */
  const [toolTab, setToolTab] = useState<
    "" | "spy" | "scrape" | "web">("");
  /** 中央视图 Tab：流程图为主编辑面，步骤列表为快速浏览面。 */
  const [viewTab, setViewTab] = useState<"list" | "graph">("graph");
  /** 目录搜索词（跨 Tab 保留）。 */
  const [catalogFilter, setCatalogFilter] = useState("");
  /** 左栏折叠（窄屏可用性）。 */
  const [leftOpen, setLeftOpen] = useState(true);
  /** 目录动作落入画布时的悬停高亮（仅底色着色）。 */
  const [dropHover, setDropHover] = useState(false);

  /** 新建节点的落点（画布流坐标）；点击插入走网格默认值。 */
  const dropPosRef = useRef(new Map<string, { x: number; y: number }>());
  /** 最近一次插入的步骤 ID → 同步后画布居中到该节点（新增必可见）。 */
  const lastAddedIdRef = useRef<string | null>(null);
  const dragDepth = useRef(0);

  // 插入后画布自动平移到新节点
  useEffect(() => {
    const id = lastAddedIdRef.current;
    if (!id || viewTab !== "graph") return;
    const node = rfNodes.find((n) => n.id === id);
    if (!node) return;
    lastAddedIdRef.current = null;
    void setCenter(node.position.x + 100, node.position.y + 40,
                   { zoom: getZoom(), duration: 400 });
  }, [rfNodes, viewTab, setCenter, getZoom]);

  // 进入流程图视图时自适应视野一次（挂载 / 切 Tab 各一次）
  useEffect(() => {
    if (viewTab !== "graph") return;
    const t = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 80);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewTab]);

  // 删除键：优先删除选中的失败跳转边（=清空源步骤 on_failure_goto），
  // 其次删除选中步骤（输入控件聚焦时不拦截；RF 内建删除已禁用）
  useEffect(() => {
    function h(e: KeyboardEvent) {
      if (e.key !== "Delete") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
                t.tagName === "SELECT" || t.isContentEditable)) return;
      if (menu || recording) return;
      if (selectedEdgeId?.startsWith("goto-")) {
        const edge = rfEdges.find((eg) => eg.id === selectedEdgeId);
        if (edge) {
          const srcIdx = steps.findIndex(
            (s, i) => (s.id || `n${i}`) === edge.source);
          if (srcIdx >= 0) updateStepAt(srcIdx, { on_failure_goto: "" });
        }
        setSelectedEdgeId(null);
        return;
      }
      if (selectedIdx == null) return;
      deleteStepAt(selectedIdx);
    }
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  // 选中下标越界回收（删除步骤后属性面板自动收起）
  useEffect(() => {
    if (selectedIdx != null && selectedIdx >= steps.length) {
      setSelectedIdx(null);
    }
  }, [steps.length, selectedIdx]);

  // steps → RF graph sync（保留用户拖动过的节点位置）
  // 边语义（P1：诚实边）：
  //   ①顺序骨干：按索引派生，不可删（deletable:false），灰色虚线；
  //   ②失败跳转：仅当 on_failure_goto 指向现存步骤 id 才画，红色实线，
  //     可选中；Delete 键删除选中边=清空源步骤字段（见 Delete 处理）。
  // 悬空 goto（目标不存在）不画边——不画不存在的东西。
  useEffect(() => {
    const idOf = (s: DStep, i: number) => s.id || `n${i}`;
    const liveIds = new Set(steps.map(idOf));
    const edges: Edge[] = [];
    for (let i = 0; i < steps.length - 1; i++) {
      edges.push({
        id: `seq-${i}`,
        source: idOf(steps[i]!, i),
        target: idOf(steps[i + 1]!, i + 1),
        type: "smoothstep",
        animated: false,
        deletable: false,
        selectable: false,
        style: { stroke: "#cbd5e1", strokeDasharray: "5 4" },
      });
    }
    steps.forEach((s, i) => {
      const target = (s.on_failure_goto || "").trim();
      if (!target || !liveIds.has(target)) return;
      edges.push({
        id: `goto-${idOf(s, i)}`,
        source: idOf(s, i),
        target,
        type: "smoothstep",
        animated: true,
        deletable: true,
        style: { stroke: "#f43f5e" },
      });
    });
    setRfNodes((prev) => {
      const prevPos = new Map(prev.map((n) => [n.id, n.position]));
      const droppedPos = dropPosRef.current;
      return steps.map((s2, i) => {
        const id = s2.id || `n${i}`;
        const gotoTarget = (s2.on_failure_goto || "").trim();
        return {
          id,
          type: "step" as const,
          position: prevPos.get(id) ?? droppedPos.get(id) ??
            { x: 220, y: i * 130 },
          data: {
            title: stepTitle(s2, catalog) || s2.id || `step_${i + 1}`,
            sub: actionSub(s2.action),
            summary: paramSummary(s2.params_json),
            index: i,
            kind: (s2.type || "") as StepNodeData["kind"],
            tone: selectedIdx === i
              ? "border-blue-500 ring-2 ring-blue-100"
              : "border-slate-200",
            hasCondition: (s2.condition || "").trim().length > 0,
            hasGoto: gotoTarget.length > 0 && liveIds.has(gotoTarget),
            loopCount: s2.body_steps?.length ?? 0,
          } satisfies StepNodeData,
        };
      });
    });
    setRfEdges(edges);
  }, [steps, selectedIdx, catalog, setRfNodes, setRfEdges]);

  // 工作台草稿拾取（Phase B 对话→设计器通道 + H2 溯源凭证）
  const sourceDraftRef = useRef<{ session_id: string; draft_id: string }
                                | null>(null);
  useEffect(() => {
    const draftKey = "apa_draft_import";
    const draft = sessionStorage.getItem(draftKey);
    sessionStorage.removeItem(draftKey); // 无条件清除，防刷新循环导入
    if (draft) {
      setYamlText(draft);
      void loadFromYaml();
      setStatusMsg("已从工作台导入流程草稿 ✓");
    }
    try {
      const src = sessionStorage.getItem("apa_draft_source");
      if (src) {
        // 溯源凭证保留在 sessionStorage（刷新后仍可保存/试运行），
        // 仅在导入新草稿时覆盖
        sourceDraftRef.current = JSON.parse(src);
      }
    } catch { /* 坏 JSON 视为无凭证 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 数据加载（流程列表；目录走共享 hook）
  useEffect(() => {
    api<ProcessInfo[]>("/api/processes").then(setProcessList).catch(() => {});
  }, []);

  const updateStepAt = useCallback(
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

  // ---- 元素拾取（桌面 / 网页，受控会话）-------------------------------------
  /** 填充模式：非空时捕获结果写入该步骤参数（element/target），而非追加。 */
  const [pick, setPick] =
    useState<{ idx: number; kind: "desktop" | "web" } | null>(null);

  function fillStepParam(idx: number, key: "element" | "target",
                         value: unknown) {
    let params: Record<string, unknown> = {};
    try {
      params = JSON.parse(steps[idx]!.params_json || "{}");
    } catch { /* 坏 JSON 直接覆盖 */ }
    params[key] = value;
    updateStepAt(idx, { params_json: JSON.stringify(params, null, 2) });
  }

  function handleSpyCapture(el: CapturedElement) {
    if (pick?.kind === "desktop" && steps[pick.idx]) {
      fillStepParam(pick.idx, "element", el);
      setStatusMsg(`已拾取 ${el.app_name} · ${el.role}` +
        ` → 填充到步骤 ${pick.idx + 1} ✓`);
      setPick(null);
    } else {
      captureSpyElement(el);
    }
  }
  const spy = useDesktopSpy(handleSpyCapture);

  // 会话结束（含面板手动停止）→ 解除填充武装
  useEffect(() => {
    if (!spy.spying && pick?.kind === "desktop") setPick(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spy.spying]);

  function captureSpyElement(el: CapturedElement) {
    setSteps(prev => {
      const step: DStep = {
        id: `spy_${prev.length + 1}`,
        type: "", action: "desktop.ui.click_element",
        target: "", condition: "", output_as: "",
        on_failure_goto: "",
        params_json: JSON.stringify({ element: el }, null, 2),
      };
      lastAddedIdRef.current = step.id;
      setSelectedIdx(prev.length);
      return [...prev, step];
    });
    setStatusMsg(`已捕获 ${el.app_name} · ${el.role}` +
      (el.title ? ` "${el.title.slice(0, 24)}"` : "") +
      " → 插入「点击界面元素」步骤");
  }

  function handleBrowserPick(el: PickPayload) {
    const css = el.locator?.css ?? el.css ?? "";
    // 协议 v2 分流：
    //   list（中间态快照）→ 仅面板展示
    //   list_done          → 填充模式写行容器选择器；否则走生成管线
    //   element / legacy   → css 写入 target（自动或按钮触发）
    if (el.kind === "list") return;

    if (el.kind === "list_done") {
      if (pick?.kind === "web" && steps[pick.idx] && el.row_css) {
        fillStepParam(pick.idx, "target", el.row_css);
        setStatusMsg(`✓ 行容器选择器已填入步骤 ${pick.idx + 1}` +
          "（批量抓取请改用面板「生成抓取步骤」）");
        setPick(null);
      }
      return;
    }

    if (!css) return;
    if (pick?.kind === "web" && steps[pick.idx]) {
      fillStepParam(pick.idx, "target", css);
      setStatusMsg(`✓ 已自动填入步骤 ${pick.idx + 1} 的 target` +
        ` <${el.tag ?? "元素"}>`);
      setPick(null);
    } else {
      const step: DStep = {
        id: `pick_${steps.length + 1}`,
        type: "", action: "browser.click",
        target: "", condition: "", output_as: "",
        on_failure_goto: "",
        params_json: JSON.stringify({ target: css }, null, 2),
      };
      setStatusMsg(
        `已选取 <${el.tag ?? "元素"}>` +
        (el.text ? ` "${el.text.slice(0, 24)}"` : "") +
        " → 插入「点击元素」步骤");
      insertStep(steps.length, step);
    }
  }

  /** 列表模式产物：生成 browser.extract_table（+可选 foreach）入画布。 */
  function handleScrapeGenerate(spec: ScrapeSpec) {
    const base = `scrape_${steps.length + 1}`;
    const pair: DStep[] = [{
      id: base,
      type: "", action: "browser.extract_table",
      target: "", condition: "", output_as: "",
      on_failure_goto: "",
      params_json: JSON.stringify({
        row_selector: spec.row_selector,
        columns: spec.columns,
        output_context: `${base}_data`,
      }, null, 2),
    }];
    if (spec.with_loop) {
      pair.push({
        id: `${base}_loop`,
        type: "foreach", action: "",
        target: "", condition: "", output_as: "",
        on_failure_goto: "",
        params_json: JSON.stringify({
          source: `{{steps.${base}.rows}}`,
          item_var: "row",
          body_steps: [],
        }, null, 2),
      });
    }
    insertStep(steps.length, pair[0]!);
    if (pair[1]) {
      setSteps(prev => {
        const at = Math.min(steps.length + 1, prev.length);
        return [...prev.slice(0, at), pair[1]!, ...prev.slice(at)];
      });
      setStatusMsg(`已生成抓取 + 循环遍历（${spec.match_count} 行 × ` +
        `${Object.keys(spec.columns).length} 列）✓ ` +
        `请在「${base}_loop」属性面板配置循环体步骤`);
    } else {
      setStatusMsg(`抓取步骤已生成 ✓ 数据引用：{{steps.${base}.rows}}`);
    }
  }

  // ---- 浏览器录制 ----------------------------------------------------------
  function startRecording() {
    if (!recording || !recording.url.startsWith("http")) return;
    post<{ session_id?: string; detail?: string }>(
      "/api/recorder/start", { url: recording.url })
      .then((r) => {
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
    post<{ yaml?: string; steps?: number }>(
      `/api/recorder/stop/${recording.sid}`, { process_id: "recorded_flow" })
      .then(async (r) => {
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

  // ---- 画布拖放建节点 -------------------------------------------------------
  function canvasDragAccept(e: React.DragEvent): boolean {
    return e.dataTransfer.types.includes("application/apa-action");
  }

  function handleCanvasDragEnter(e: React.DragEvent) {
    if (!canvasDragAccept(e)) return;
    dragDepth.current += 1;
    setDropHover(true);
  }

  function handleCanvasDragOver(e: React.DragEvent) {
    if (!canvasDragAccept(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }

  function handleCanvasDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDropHover(false);
  }

  function handleCanvasDrop(e: React.DragEvent) {
    dragDepth.current = 0;
    setDropHover(false);
    const action = readDnDAction(e.nativeEvent as DragEvent);
    if (!action) return;
    e.preventDefault();
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const step = stepFromAction(action, steps.length, catalog);
    lastAddedIdRef.current = step.id;
    dropPosRef.current.set(step.id, pos);
    setSelectedIdx(steps.length);
    setSteps((prev) => [...prev, step]);
    setStatusMsg(`已从目录拖入 ${action} ✓`);
  }

  // ---- 步骤增删改 / 排序 -----------------------------------------------------
  function moveStep(from: number, to: number) {
    if (from === to) return;
    setSteps((prev) => {
      if (from < 0 || from >= prev.length || to < 0 || to >= prev.length) {
        return prev;
      }
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved!);
      return next;
    });
    setSelectedIdx(to);
  }

  function handleCardDrop(target: number, e: React.DragEvent) {
    // 阻断向画布容器冒泡——否则目录动作会二次插入；
    // 冒泡被阻断后容器 onDrop 不触发，需就地复位拖入高亮状态
    e.stopPropagation();
    dragDepth.current = 0;
    setDropHover(false);
    const from = readDnDStepIndex(e.nativeEvent as DragEvent);
    if (from === null) {
      // 目录动作落到步骤卡上 → 插到该卡之后
      const action = readDnDAction(e.nativeEvent as DragEvent);
      if (action) {
        insertStep(target + 1,
                   stepFromAction(action, target + 1, catalog));
      }
      e.preventDefault();
      return;
    }
    e.preventDefault();
    moveStep(from, target);
  }

  function insertStep(at: number, step: DStep) {
    lastAddedIdRef.current = step.id;
    setSteps((prev) => {
      const at2 = Math.max(0, Math.min(at, prev.length));
      return [...prev.slice(0, at2), step, ...prev.slice(at2)];
    });
    setSelectedIdx(at);
  }

  function duplicateStep(idx: number) {
    setSteps((prev) => {
      if (idx < 0 || idx >= prev.length) return prev;
      const src = prev[idx]!;
      const copy: DStep = { ...src,
        id: `${src.id || `step_${idx + 1}`}_copy${Date.now()
          .toString(36).slice(-3)}` };
      return [...prev.slice(0, idx + 1), copy, ...prev.slice(idx + 1)];
    });
    setMenu(null);
  }

  function deleteStepAt(idx: number) {
    setSteps((prev) => prev.filter((_, i) => i !== idx));
    setSelectedIdx(null);
    setMenu(null);
  }

  function blankAt(at: number) {
    insertStep(at, blankStep(at));
    setMenu(null);
  }

  async function syncToYaml() {
    try {
      const form = buildForm();
      const d = await studioRpc<{ yaml: string }>(
        "yaml.from_form", { form });
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
      const d = await studioRpc<FormResponse>(
        "yaml.to_form", { yaml: yamlText });
      setMetaId(d.form.id);
      setTriggerName(d.form.trigger_name);
      setMaxActions(d.form.max_actions);
      setSteps(d.form.steps.map(s => ({
        ...s, params_json:
          typeof s.params_json === "string" ? s.params_json : "{}",
      })));
      setStatusMsg("已从 YAML 加载表单 ✓");
    } catch (e) {
      setStatusMsg(`解析失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  async function save() {
    try {
      // steps[] 是唯一真相源：保存前先表单→YAML，杜绝存出陈旧/空 YAML
      const sync = await studioRpc<{ yaml: string }>(
        "yaml.from_form", { form: buildForm() });
      setYamlText(sync.yaml);
      // H3：保存走 Studio RPC（含计划态确认门）
      await studioRpc("process.save", {
        id: metaId || "untitled", yaml: sync.yaml,
        ...(sourceDraftRef.current ?? {}),
      });
      setStatusMsg(`已保存 ${metaId} ✓`);
      void refreshProcessList();
    } catch (e) {
      setStatusMsg(`保存失败: ${e instanceof Error ? e.message : e}`);
    }
  }

  function refreshProcessList() {
    studioRpc<{ jobs?: unknown; sessions?: unknown;
                processes?: ProcessInfo[] }>("processes.list")
      .then(d => setProcessList(d.processes ?? []))
      .catch(() => {});
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

  function addGeneratedSteps(genSteps: unknown[], label: string) {
    setSteps(prev => {
      const converted: DStep[] = (genSteps as Record<string, unknown>[]).map(
        (raw, i) => {
          const { params, ...rest } = raw as Record<string, unknown>;
          return {
            ...(rest as unknown as DStep),
            id: String(raw.id ?? `gen_${prev.length + i + 1}`),
            type: String(raw.type ?? ""),
            action: String(raw.action ?? ""),
            target: "",
            condition: "",
            output_as: "",
            on_failure_goto: "",
            params_json: JSON.stringify(params ?? {}, null, 2),
          };
        });
      if (converted.length) {
        lastAddedIdRef.current =
          converted[converted.length - 1]!.id;
      }
      return [...prev, ...converted];
    });
    setStatusMsg(`抓取向导：已插入 ${label} ✓`);
  }

  const selectedStep = selectedIdx != null ? steps[selectedIdx] : undefined;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50">

      {/* ===== 工具栏 ===== */}
      <header className="flex items-center gap-2 px-3 py-2 border-b
                         border-slate-200 bg-white shrink-0 z-10">
        <EngineChip />
        <div className="h-4 w-px bg-slate-200" />
        <input className="w-44 h-8 px-2 text-xs font-medium bg-transparent
                          border border-transparent rounded-md
                          hover:border-slate-200 focus:border-slate-300
                          focus:bg-white outline-none"
          placeholder="流程 ID" value={metaId}
          onChange={e => setMetaId(e.target.value)} />
        <input className="w-56 h-8 px-2 text-xs bg-transparent
                          border border-transparent rounded-md
                          hover:border-slate-200 focus:border-slate-300
                          focus:bg-white outline-none"
          placeholder="触发事件（可选）"
          value={triggerName}
          onChange={e => setTriggerName(e.target.value)} />

        <div className="ml-auto flex items-center gap-1.5">
          <Button size="sm" variant="ghost"
            onClick={() => void openFile(currentFile)}
            disabled={!currentFile} title="重新加载已保存版本">
            <FolderOpen size={13} /> 重载
          </Button>
          <Button size="sm" variant="secondary"
            onClick={() => { setYamlOpen(o => !o); setRunOpen(false); }}>
            <Code2 size={13} /> YAML
          </Button>
          <Button size="sm" variant="secondary"
            onClick={() => {
              setRunOpen(o => !o);
              setYamlOpen(false);
              void syncToYaml();  // 试运行吃当前步骤，先同步投影
            }}>
            <Terminal size={13} /> 试运行
          </Button>
          <Button size="sm" variant="secondary"
            onClick={() => setRecording({ sid: "", url: "https://",
                                          events: 0, phase: "enter" })}>
            <SquareDot size={13} className="text-red-500" /> 录制
          </Button>
          <Button size="sm" variant="primary" onClick={() => void save()}>
            <Save size={13} /> 保存
          </Button>
        </div>
      </header>

      {/* ===== 三栏主体 ===== */}
      <div className="flex-1 flex min-h-0">

        {/* 左：目录 / 工具 / 资产 */}
        <aside className={`border-r border-slate-200 bg-white shrink-0
                           flex flex-col overflow-hidden transition-all ${
            leftOpen ? "w-[248px]" : "w-9"}`}>
          {leftOpen ? (
            <>
              <nav className="flex items-center gap-1 px-2 pt-2 pb-1
                              border-b border-slate-100">
                {([["", "动作"], ["spy", "拾取"], ["web", "网页"],
                   ["scrape", "抓取"]] as const).map(([k, label]) => (
                  <button key={k} onClick={() => setToolTab(k)}
                    className={`h-6 px-2 rounded text-[11px] font-medium
                                transition-colors ${toolTab === k
                      ? "bg-zinc-900 text-white"
                      : "text-slate-500 hover:bg-slate-100"}`}>
                    {label}
                  </button>
                ))}
                <IconButton label="收起侧栏" className="ml-auto"
                            onClick={() => setLeftOpen(false)}>
                  <PanelLeftClose size={13} />
                </IconButton>
              </nav>
              <div className="flex-1 overflow-y-auto p-2 min-h-0">
                {toolTab === "" && (
                  <CatalogPanel
                    filter={catalogFilter}
                    onFilterChange={setCatalogFilter}
                    onInsert={(action: string) =>
                      insertStep(steps.length,
                        stepFromAction(action, steps.length, catalog))} />
                )}
                {toolTab === "spy" && (
                  <SpyPanel spy={spy}
                    targetHint={pick?.kind === "desktop"
                      ? `步骤 ${pick.idx + 1}`
                      : null} />
                )}
                {toolTab === "web" && (
                  <BrowserPickPanel onPick={handleBrowserPick}
                    onScrapeGenerate={handleScrapeGenerate}
                    targetHint={pick?.kind === "web"
                      ? `步骤 ${pick.idx + 1}`
                      : null} />
                )}
                {toolTab === "scrape" &&
                  <ScrapePanel onGenerate={addGeneratedSteps} />}
              </div>
              <div className="border-t border-slate-100 max-h-[32%]
                              overflow-y-auto shrink-0">
                <TemplateLibrary onPick={importTemplate} />
                <details className="mt-1 px-2 pb-2">
                  <summary className="text-xs text-slate-400 cursor-pointer
                                      py-0.5">
                    已保存流程 ({processList.filter(pl => pl.valid).length})
                  </summary>
                  <div className="mt-1 space-y-0.5">
                    {processList.map(pl => (
                      <div key={pl.id}
                           onClick={() => void openFile(pl.id)}
                           className="flex items-center justify-between
                                      px-1.5 py-1 text-xs hover:bg-slate-50
                                      rounded cursor-pointer">
                        <span className="font-mono truncate">{pl.id}</span>
                        <Badge tone={pl.valid ? "green" : "red"}>
                          {pl.valid ? `${pl.steps}` : "invalid"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center pt-2 gap-2">
              <IconButton label="展开侧栏" onClick={() => setLeftOpen(true)}>
                <PanelLeftOpen size={13} />
              </IconButton>
              <button onClick={() => setLeftOpen(true)}
                className="text-[10px] text-slate-400 hover:text-slate-600"
                style={{ writingMode: "vertical-rl" }}>
                动作目录
              </button>
            </div>
          )}
        </aside>

        {/* 中：双视图（流程图主编辑面 / 步骤列表） */}
        <section className="flex-1 min-w-0 flex flex-col">
          <nav className="flex items-center gap-2 px-3 pt-2 shrink-0">
            <div className="inline-flex bg-slate-200/60 rounded-lg p-0.5">
              {([["graph", "流程图", Workflow],
                 ["list", "步骤列表", ListTree]] as const).map(
                ([vk, vlabel, Icon]) => (
                  <button key={vk} onClick={() => setViewTab(vk)}
                    className={`h-6 px-2.5 rounded-md text-[11px]
                                font-medium inline-flex items-center gap-1
                                transition-colors ${viewTab === vk
                      ? "bg-white text-zinc-900 shadow-sm"
                      : "text-slate-500 hover:text-slate-700"}`}>
                    <Icon size={12} /> {vlabel}
                    <span className="text-slate-400">{steps.length}</span>
                  </button>
                ))}
            </div>
            <button onClick={() =>
              insertStep(steps.length, blankStep(steps.length))}
              className="ml-auto h-6 px-2 inline-flex items-center gap-1
                         text-[11px] font-medium text-slate-500
                         hover:text-zinc-900 hover:bg-slate-100 rounded-md">
              <Plus size={12} /> 添加步骤
            </button>
          </nav>

          <div className="flex-1 min-h-0 p-3 pt-2">
            <div
              className={`relative h-full rounded-xl border
                          overflow-hidden transition-colors ${
                dropHover
                  ? "bg-blue-50/50 border-blue-200"
                  : "bg-white border-slate-200"}`}
              onDragEnter={handleCanvasDragEnter}
              onDragOver={handleCanvasDragOver}
              onDragLeave={handleCanvasDragLeave}
              onDrop={handleCanvasDrop}>

              {/* 画布控件：整理布局 / 适配视图 */}
              {viewTab === "graph" && steps.length > 0 && (
                <div className="absolute top-2 right-2 z-10 flex gap-1
                                bg-white/90 rounded-md p-0.5">
                  <IconButton label="整理布局"
                    onClick={() => {
                      setRfNodes(prev => prev.map((n, i) => ({
                        ...n, position: { x: 220, y: i * 130 },
                      })));
                      setTimeout(() => fitView(
                        { padding: 0.15, duration: 300 }), 60);
                    }}>
                    <AlignVerticalSpaceAround size={13} />
                  </IconButton>
                  <IconButton label="适配视图"
                    onClick={() => fitView({ padding: 0.15, duration: 300 })}>
                    <Maximize size={13} />
                  </IconButton>
                </div>
              )}

              {viewTab === "graph" && (
                <ReactFlow
                  nodes={rfNodes} edges={rfEdges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  nodeTypes={nodeTypes}
                  deleteKeyCode={null}
                  minZoom={0.2}
                  maxZoom={1.5}
                  onNodeClick={(_, node) => {
                    const idx = (node.data as StepNodeData).index;
                    if (idx != null) setSelectedIdx(idx);
                    setSelectedEdgeId(null);
                  }}
                  onPaneClick={() => {
                    setSelectedIdx(null);
                    setSelectedEdgeId(null);
                  }}
                  onEdgeClick={(_, edge) => {
                    // 只有失败跳转边可选中；骨干边 selectable:false 点不中。
                    if (edge.id.startsWith("goto-")) {
                      setSelectedEdgeId(edge.id);
                    }
                  }}
                  onConnect={(params) => {
                    // P1-T4：约束连线——只允许创建失败跳转边。
                    // 守卫：①拒自连；②源/目标步骤必须有真实 id
                    // （回退 n{i} 无意义，排序后即失效）；③目标必须存在。
                    // 通过则写源步骤 on_failure_goto=目标 id（覆盖旧值，
                    // 一步骤至多一条跳转边，与引擎语义一致）。
                    const { source, target } = params;
                    if (!source || !target || source === target) return;
                    const srcIdx = steps.findIndex(
                      (s, i) => (s.id || `n${i}`) === source);
                    const tgt = steps.find(
                      (s, i) => (s.id || `n${i}`) === target);
                    if (srcIdx < 0 || !tgt || !tgt.id) return;
                    updateStepAt(srcIdx, { on_failure_goto: tgt.id });
                    setSelectedIdx(srcIdx);
                    setStatusMsg(`已设置失败跳转 → ${tgt.id} ✓`);
                  }}
                  onNodeDragStop={(_, node, nodes) => {
                    // P1-T2：画布拖拽=排序。按 y（同行按 x）换算新索引，
                    // 回写 steps；顺序不变则 no-op。
                    const oldIdx = (node.data as StepNodeData).index;
                    if (oldIdx == null) return;
                    const order = [...nodes].sort((a, b) =>
                      a.position.y - b.position.y ||
                      a.position.x - b.position.x);
                    const newIdx = order.findIndex((n) => n.id === node.id);
                    if (newIdx >= 0 && newIdx !== oldIdx) {
                      moveStep(oldIdx, newIdx);
                    }
                  }}
                >
                  <Background variant={BackgroundVariant.Dots}
                              gap={20} size={1.5} color="#cbd5e1" />
                  <Controls showInteractive={false} />
                  <MiniMap pannable zoomable
                           className="!bg-slate-50 !border-slate-200"
                           nodeColor="#e2e8f0" maskColor="#f1f5f9cc" />
                </ReactFlow>
              )}

              {viewTab === "list" && (
                <div className="absolute inset-0 overflow-y-auto p-3">
                  <div className="max-w-[720px] mx-auto space-y-2">
                    {steps.map((s, i) => {
                      const title = stepTitle(s, catalog) ||
                        (s.type ? "" : "(未设置动作)");
                      const sub = actionSub(s.action);
                      const summary = paramSummary(s.params_json);
                      return (
                        <div key={s.id || i}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData(
                              "application/apa-step-index", String(i));
                            e.dataTransfer.setData("text/plain", String(i));
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          onDragOver={(e) => {
                            if (e.dataTransfer.types.includes(
                                  "application/apa-step-index") ||
                                e.dataTransfer.types.includes(
                                  "application/apa-action")) {
                              e.preventDefault();
                              if (dragOverIdx !== i) setDragOverIdx(i);
                            }
                          }}
                          onDragLeave={() => {
                            if (dragOverIdx === i) setDragOverIdx(null);
                          }}
                          onDrop={(e) => {
                            setDragOverIdx(null);
                            handleCardDrop(i, e);
                          }}
                          onClick={() => setSelectedIdx(i)}
                          onContextMenu={(e) => {
                            e.preventDefault();
                            setMenu({ idx: i, x: e.clientX, y: e.clientY });
                          }}
                          className={`group cursor-grab active:cursor-grabbing
                                      rounded-lg border px-3 py-2
                                      transition-[border-color,box-shadow,background-color]
                                      duration-150 ${
                            selectedIdx === i
                              ? "ring-1 ring-blue-300 border-blue-300 bg-blue-50"
                              : dragOverIdx === i
                                ? "border-dashed border-blue-400 bg-blue-50/60"
                                : "border-slate-200 bg-white hover:border-slate-300"}`}>
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="inline-flex items-center
                                             justify-center w-4 h-4 shrink-0
                                             rounded-full bg-zinc-900
                                             text-white text-[9px]
                                             font-semibold">
                              {i + 1}
                            </span>
                            <span className="font-medium text-xs
                                             text-slate-800 truncate">
                              {title || `[${s.type}]`}
                            </span>
                            {!sub && s.type && (
                              <span className="text-[9px] leading-none
                                               rounded bg-violet-50
                                               text-violet-500 px-1 py-0.5
                                               font-medium shrink-0">
                                {s.type}
                              </span>
                            )}
                            <span className="ml-auto hidden group-hover:flex
                                             items-center gap-0.5 shrink-0">
                              <IconButton label="复制步骤"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            duplicateStep(i);
                                          }}>
                                <Copy size={12} />
                              </IconButton>
                              <IconButton label="删除步骤"
                                          className="hover:text-red-600"
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            deleteStepAt(i);
                                          }}>
                                <Trash2 size={12} />
                              </IconButton>
                            </span>
                          </div>
                          {(sub || summary) && (
                            <p className="mt-0.5 ml-6 text-[10px] truncate
                                          font-mono text-slate-400">
                              {sub}{sub && summary ? " · " : ""}
                              {summary && (
                                <span className="font-sans text-slate-300">
                                  {summary}
                                </span>
                              )}
                            </p>
                          )}
                        </div>
                      );
                    })}
                    <button onClick={() =>
                      insertStep(steps.length, blankStep(steps.length))}
                      className="w-full py-2 text-xs border border-dashed
                                 border-slate-300 rounded-lg text-slate-400
                                 hover:border-blue-400 hover:text-blue-500
                                 transition-colors">
                      ＋ 添加步骤
                    </button>
                  </div>
                </div>
              )}

              {/* 空态引导：画布无节点时 */}
              {viewTab === "graph" && steps.length === 0 && (
                <div className="absolute inset-0 flex items-center
                                justify-center pointer-events-none">
                  <div className="text-center space-y-1">
                    <Workflow size={28} className="mx-auto text-slate-200" />
                    <p className="text-sm text-slate-300">
                      从左侧拖入动作，或点击动作添加第一步
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* 右：属性面板（选中步骤时出现） */}
        {selectedStep && selectedIdx != null && (
          <StepInspector
            step={selectedStep}
            index={selectedIdx}
            meta={selectedStep.action
              ? catalog[selectedStep.action]
              : undefined}
            availableVars={availableVariables(steps, selectedIdx)}
            onChange={(patch) => updateStepAt(selectedIdx, patch)}
            onPickFromScreen={() => {
              setToolTab("spy");
              setLeftOpen(true);
              setPick({ idx: selectedIdx, kind: "desktop" });
              if (!spy.spying) spy.start();
            }}
            onPickFromPage={() => {
              setToolTab("web");
              setLeftOpen(true);
              setPick({ idx: selectedIdx, kind: "web" });
            }}
            onDuplicate={() => duplicateStep(selectedIdx)}
            onDelete={() => deleteStepAt(selectedIdx)}
            onClose={() => setSelectedIdx(null)}
          />
        )}
      </div>

      {/* ===== YAML 抽屉 ===== */}
      <Drawer open={yamlOpen} onClose={() => setYamlOpen(false)}
              height={320} title="YAML（专家通道）">
        <div className="p-3 space-y-2">
          <textarea
            className="w-full p-2 text-xs font-mono border rounded resize-y
                       min-h-[160px] leading-relaxed outline-none
                       focus:border-slate-400"
            spellCheck={false}
            rows={10} value={yamlText}
            onChange={e => setYamlText(e.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" variant="secondary"
              onClick={() => void syncToYaml()}>表单 → YAML</Button>
            <Button size="sm" variant="secondary"
              onClick={() => void loadFromYaml()}>YAML → 表单</Button>
          </div>
        </div>
      </Drawer>

      {/* ===== 试运行抽屉 ===== */}
      <Drawer open={runOpen} onClose={() => setRunOpen(false)}
              height={280} title="试运行">
        <div className="p-3">
          <TestRunPanel yaml={yamlText}
            sessionId={sourceDraftRef.current?.session_id}
            draftId={sourceDraftRef.current?.draft_id} />
        </div>
      </Drawer>

      {/* ===== 状态栏 ===== */}
      <footer className="px-4 py-1 bg-slate-900 text-slate-300 text-xs
                         flex justify-between shrink-0">
        <span>{statusMsg}</span>
        <StudioEventTicker />
        <span>{currentFile}</span>
      </footer>

      {/* ===== 步骤右键菜单 ===== */}
      {menu && (
        <div className="fixed inset-0 z-40" onClick={() => setMenu(null)}
             onContextMenu={(e) => { e.preventDefault(); setMenu(null); }}>
          <div style={{ left: menu.x, top: menu.y }}
               className="absolute bg-white border border-slate-200
                          rounded-lg shadow-lg py-1 w-36 text-xs">
            <button onClick={() => duplicateStep(menu.idx)}
              className="w-full px-3 py-1.5 text-left hover:bg-slate-50">
              ⧉ 复制步骤
            </button>
            <button onClick={() => blankAt(menu.idx)}
              className="w-full px-3 py-1.5 text-left hover:bg-slate-50">
              ↑ 在前面插入
            </button>
            <button onClick={() => blankAt(menu.idx + 1)}
              className="w-full px-3 py-1.5 text-left hover:bg-slate-50">
              ↓ 在后面插入
            </button>
            <div className="my-0.5 border-t border-slate-100" />
            <button onClick={() => deleteStepAt(menu.idx)}
              className="w-full px-3 py-1.5 text-left text-red-600
                         hover:bg-red-50">
              ✕ 删除步骤
            </button>
          </div>
        </div>
      )}

      {/* ===== 录制模态 ===== */}
      {recording && (
        <div className="fixed inset-0 bg-black/40 flex items-center
                        justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-5 w-[380px]">
            <p className="text-sm font-semibold mb-3">浏览器操作录制</p>
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
                <p className="text-xs text-slate-500 mb-1">{recording.url}</p>
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

/** Studio notification 心跳条（H3 二期）：状态栏右侧显示最新下行事件。 */
function StudioEventTicker() {
  const [note, setNote] = useState("");
  useStudioEvents((method, payload) => {
    if (method === "run.step") {
      setNote(`▶ ${String(payload.action ?? "")} · ` +
              `${String(payload.status ?? "")}`);
    } else if (method === "approval.elicit") {
      setNote(`⏸ 待审批：${String(payload.prompt ?? "")}`);
    }
  });
  if (!note) return null;
  return <span className="text-slate-500 font-mono">{note}</span>;
}

/** 模板库侧栏：从 /api/templates 拉取，点击导入画布。 */
function TemplateLibrary({ onPick }: { onPick: (t: TemplateInfo) => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TemplateInfo[]>([]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !items.length) {
      studioRpc<{ templates: TemplateInfo[] }>("templates.list")
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
            {t.name}
          </div>
        ))}
        {!items.length && (
          <p className="text-xs text-slate-300">（加载中…）</p>
        )}
      </div>
    </details>
  );
}
