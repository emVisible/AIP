/**
 * 上下文工具浮层（P3：拾取三面板的新家）。
 *
 * 左栏 Tab 已移除；SpyPanel / BrowserPickPanel / ScrapePanel 本体不动，
 * 只换挂载位置。由 Inspector 拾取按钮（带 pick 上下文）或画布工具栏
 * （无上下文）打开；回填成功 / 会话结束 / 手动关闭时由父层关闭。
 */
import { useEffect } from "react";
import { X } from "lucide-react";

import type { useDesktopSpy } from "../../hooks/useDesktopSpy";
import { SpyPanel } from "./SpyPanel";
import { BrowserPickPanel, type PickPayload, type ScrapeSpec }
  from "./BrowserPickPanel";
import { ScrapePanel } from "./ScrapePanel";

export type FloatKind = "spy" | "web" | "scrape";

type Spy = ReturnType<typeof useDesktopSpy>;

const KIND_LABEL: Record<FloatKind, string> = {
  spy: "桌面拾取",
  web: "网页拾取",
  scrape: "抓取向导",
};

export function ToolFloatPanel({ kind, onKindChange, onClose,
                                 hint, spy, targetHint,
                                 onPick, onScrapeGenerate, onGenerate }: {
  kind: FloatKind;
  onKindChange: (k: FloatKind) => void;
  onClose: () => void;
  /** 上下文提示，如"正在为步骤 3 拾取"；无上下文时为 null。 */
  hint?: string | null;
  spy: Spy;
  targetHint?: string | null;
  onPick: (el: PickPayload) => void;
  onScrapeGenerate: (spec: ScrapeSpec) => void;
  onGenerate: (steps: unknown[], label: string) => void;
}) {
  // Esc 关闭
  useEffect(() => {
    function h(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const kinds: FloatKind[] = ["spy", "web", "scrape"];

  return (
    <div className="fixed right-4 top-16 bottom-4 w-[360px] z-50
                    flex flex-col rounded-xl border border-slate-200
                    bg-white shadow-[0_8px_30px_rgba(0,0,0,0.12)]
                    animate-pop-in">
      <div className="flex items-center gap-1 px-2 pt-2 pb-1
                      border-b border-slate-100">
        {kinds.map(k => (
          <button key={k} onClick={() => onKindChange(k)}
            className={`h-6 px-2 rounded text-[11px] font-medium
                        transition-colors duration-150 ${kind === k
              ? "bg-zinc-900 text-white"
              : "text-slate-500 hover:bg-slate-100"}`}>
            {KIND_LABEL[k]}
          </button>
        ))}
        <button onClick={onClose} title="关闭（Esc）"
          className="ml-auto inline-flex items-center justify-center
                     w-6 h-6 rounded-md text-slate-400 hover:text-slate-700
                     hover:bg-slate-100 transition-all duration-150
                     active:scale-90">
          <X size={13} />
        </button>
      </div>
      {hint && (
        <p className="px-3 py-1.5 text-[11px] text-violet-600
                      bg-violet-50/60 border-b border-violet-100
                      animate-fade-in">
          ◎ {hint}
        </p>
      )}
      <div className="flex-1 overflow-y-auto p-2 min-h-0">
        {kind === "spy" && <SpyPanel spy={spy} targetHint={targetHint} />}
        {kind === "web" && (
          <BrowserPickPanel onPick={onPick}
            onScrapeGenerate={onScrapeGenerate} targetHint={targetHint} />
        )}
        {kind === "scrape" && <ScrapePanel onGenerate={onGenerate} />}
      </div>
    </div>
  );
}
