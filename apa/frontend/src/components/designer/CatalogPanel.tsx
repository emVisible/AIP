import { useMemo, useState } from "react";
import {
  Bell,
  Binary,
  Braces,
  Building2,
  CalendarClock,
  ClipboardList,
  Cog,
  Database,
  FileText,
  FolderOpen,
  Globe,
  Hash,
  Layers,
  Mail,
  Monitor,
  PlayCircle,
  ScanText,
  Sheet,
  Sparkles,
  Terminal,
  Type,
  UserCheck,
  Webhook,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ActionMeta } from "../../api/types";
import { cn } from "../../lib/utils";
import { FLOW_NODES, actionSub, actionTitle } from "../../lib/actionDisplay";
import { useActionCatalog } from "../../hooks/useActionCatalog";

/** 域 → 图标映射（目录分组标题）。 */
const DOMAIN_ICONS: Record<string, LucideIcon> = {
  browser: Globe,
  excel: Sheet,
  data: Database,
  string: Type,
  desktop: Monitor,
  ocr: ScanText,
  email: Mail,
  file: FolderOpen,
  api: Webhook,
  encode: Binary,
  json: Braces,
  dt: CalendarClock,
  hash: Hash,
  doc: FileText,
  llm: Sparkles,
  notify: Bell,
  db: Database,
  shell: Terminal,
  core: Cog,
  context: Layers,
  erp: Building2,
  human: UserCheck,
  clipboard: ClipboardList,
  session: PlayCircle,
};

/** 域 → 显示名映射（目录分组标题）。 */
const DOMAIN_LABELS: Record<string, string> = {
  browser: "浏览器",
  excel: "Excel",
  data: "数据",
  string: "字符串",
  desktop: "桌面",
  ocr: "OCR",
  email: "邮件",
  file: "文件",
  api: "API",
  encode: "编码",
  json: "JSON",
  dt: "日期时间",
  hash: "哈希",
  doc: "文档",
  llm: "LLM",
  notify: "通知",
  db: "数据库",
  shell: "Shell",
  core: "核心",
  context: "上下文",
  erp: "ERP",
  human: "人工",
  clipboard: "剪贴板",
  session: "会话",
};

/** 动作目录侧栏 —— 加载态 / 错误重试 / 搜索 / 拖拽源。 */
export function CatalogPanel({ onInsert, filter, onFilterChange }: {
  onInsert: (action: string) => void;
  filter?: string;
  onFilterChange?: (v: string) => void;
}) {
  const [inner, setInner] = useState("");
  const filter_ = filter ?? inner;
  const setFilter = onFilterChange ?? setInner;

  const { catalog, isLoading, isError, refetch } = useActionCatalog();

  const flowItems = useMemo(() => {
    const q = filter_.toLowerCase();
    return FLOW_NODES.filter(
      ([n, d]) =>
        !q || n.toLowerCase().includes(q) || d.toLowerCase().includes(q),
    );
  }, [filter_]);

  const groups = useMemo(() => {
    const q = filter_.toLowerCase();
    const byDomain: Record<string, [string, ActionMeta][]> = {};
    for (const [name, meta] of Object.entries(
      catalog as Record<string, ActionMeta>,
    )) {
      const haystack = name + " " + (meta.label_cn ?? "") + " " +
        (meta.description ?? "");
      if (q && !haystack.toLowerCase().includes(q)) continue;
      const domain = name.split(".")[0] ?? "other";
      (byDomain[domain] ??= []).push([name, meta]);
    }
    return byDomain;
  }, [catalog]);

  const totalCount = Object.keys(catalog as Record<string, unknown>).length +
    FLOW_NODES.length;

  function renderAction(name: string, meta: ActionMeta,
                         tone?: "violet") {
    const title = actionTitle(name, { [name]: meta });
    const sub = actionSub(name, { [name]: meta });
    return (
      <div
        key={name}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("application/apa-action", name);
          e.dataTransfer.setData("text/plain", name);
          e.dataTransfer.effectAllowed = "copy";
        }}
        onClick={() => onInsert(name)}
        className={cn(
          "px-2 py-1 cursor-grab active:cursor-grabbing rounded group",
          "transition-all duration-150 hover:translate-x-[1px] active:scale-[.99]",
          tone === "violet" ? "hover:bg-violet-50" : "hover:bg-blue-50",
        )}
        title={(meta.description ?? "") +
               ` [${meta.risk} · ${meta.executor_domain}]`}
      >
        <div className="flex justify-between items-center gap-1">
          <span className="truncate text-xs font-medium text-slate-700">
            {title}
          </span>
          <span
            className={`text-[10px] rounded px-1 shrink-0 ${
              tone === "violet"
                ? "bg-violet-100 text-violet-600"
                : meta.risk.startsWith("L0")
                  ? "text-slate-300"
                  : meta.risk.startsWith("L1")
                    ? "text-amber-400"
                    : "text-red-400"
            }`}
          >
            {tone === "violet" ? "CTL" : meta.risk}
          </span>
        </div>
        {sub && (
          <p className="truncate text-[10px] font-mono text-slate-300
                        group-hover:text-slate-400 leading-tight">
            {sub}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {/* 搜索框 + 计数 */}
      <div className="flex items-center gap-1.5">
        <input
          className="flex-1 min-w-0 px-2 py-1 text-xs border border-slate-200
                     rounded focus:border-slate-400 outline-none"
          placeholder={`搜索 ${totalCount} 个动作…`}
          value={filter_}
          onChange={(e) => setFilter(e.target.value)}
        />
        {totalCount > 0 && (
          <span className="text-[10px] text-slate-300 shrink-0">
            {totalCount}
          </span>
        )}
      </div>

      <div className="overflow-y-auto">
        {/* 加载骨架 */}
        {isLoading && (
          <div className="space-y-1 p-1 animate-pulse">
            {[...Array(8)].map((_, i) => (
              <div key={i}
                   className="h-7 bg-slate-100 rounded"
                   style={{ width: `${85 - i * 6}%` }} />
            ))}
          </div>
        )}

        {/* 错误重试 */}
        {isError && (
          <div className="p-2 text-center space-y-1.5">
            <p className="text-xs text-red-400">动作目录加载失败</p>
            <button
              onClick={() => void refetch()}
              className="text-xs text-blue-500 hover:text-blue-700
                         underline underline-offset-2">
              重试
            </button>
          </div>
        )}

        {/* 流程控制节点 */}
        {!isLoading && !isError && flowItems.length > 0 && (
          <div>
            <p className="flex items-center gap-1 text-[10px] font-semibold
                          text-slate-400 uppercase tracking-wide px-1 pt-2">
              <Workflow size={11} /> 流程控制
            </p>
            {flowItems.map(([name, desc]) =>
              renderAction(name, { description: desc,
                                   risk: "L0",
                                   executor_domain: "core",
                                   idempotency: "",
                                   deprecated: false,
                                   params: null }, "violet"),
            )}
          </div>
        )}

        {/* Registry 动作（按域分组） */}
        {!isLoading && !isError &&
          Object.entries(groups).map(([domain, items]) => {
            const Icon = DOMAIN_ICONS[domain];
            return (
              <div key={domain}>
                <p className="flex items-center gap-1 text-[10px]
                              font-semibold text-slate-400 uppercase
                              tracking-wide px-1 pt-2">
                  {Icon && <Icon size={11} />}
                  {DOMAIN_LABELS[domain] ?? domain}
                  <span className="ml-0.5 font-normal">
                    ({items.length})
                  </span>
                </p>
                {items.map(([name, meta]) => renderAction(name, meta))}
              </div>
            );
          })}

        {/* 空搜索结果 */}
        {!isLoading && !isError &&
         !Object.keys(groups).length && !!filter_ && (
          <p className="text-xs text-slate-300 p-2 text-center">
            无匹配「{filter_}」的动作
          </p>
        )}
      </div>
    </div>
  );
}
