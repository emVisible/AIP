import { useEffect, useRef, useState } from "react";

import { post } from "../../api/client";

/** SpyService hover 帧。 */
interface HoverFrame {
  type: string;
  version?: number;
  element?: {
    role: string;
    title: string;
    value: string | null;
    app_name: string;
    pid: number;
    bounds: { x: number; y: number; w: number; h: number } | null;
  } | null;
}

export interface CapturedElement {
  role: string;
  title: string;
  value: string | null;
  app_name: string;
  pid: number;
  bounds: { x: number; y: number; w: number; h: number } | null;
  ax_path: unknown[];
}

/**
 * 桌面拾取面板（影刀 Ctrl 悬停体验）。
 * start → SSE hover 流（Electron overlay 高亮跟随）→ capture 存为步骤。
 * 纯浏览器环境（无 Electron）也能用：只是没有高亮框。
 */
export function SpyPanel({ onCapture }: {
  onCapture: (el: CapturedElement) => void;
}) {
  const [spying, setSpying] = useState(false);
  const [live, setLive] = useState<HoverFrame["element"]>(null);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);
  const liveRef = useRef<HoverFrame["element"]>(null);
  liveRef.current = live;

  function cleanup() {
    esRef.current?.close();
    esRef.current = null;
    window.apaDesktop?.stopSpyOverlay?.();
  }

  useEffect(() => () => {
    if (esRef.current) {
      esRef.current.close();
      void post("/api/spy/stop", {});
    }
  }, []);

  async function start() {
    setError("");
    try {
      await post("/api/spy/start", {});
      setSpying(true);
      setLive(null);
      window.apaDesktop?.startSpyOverlay?.();

      const es = new EventSource("/api/spy/stream");
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const frame: HoverFrame = JSON.parse(ev.data);
          if (frame.type === "hover") {
            setLive(frame.element ?? null);
            const b = frame.element?.bounds;
            if (b && b.w > 0) {
              const el = frame.element!;
              window.apaDesktop?.spyBounds?.(b,
                `${el.app_name} · ${el.role}` +
                (el.title ? ` · ${el.title.slice(0, 30)}` : ""));
            }
          } else if (frame.type === "ended" || frame.type === "timeout") {
            stop();
          }
        } catch { /* 忽略坏帧 */ }
      };
      es.onerror = () => { /* 断线由 stop 兜底 */ };
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function stop() {
    cleanup();
    setSpying(false);
    void post("/api/spy/stop", {});
  }

  async function capture() {
    try {
      const r = await post<{ element?: CapturedElement }>("/api/spy/capture", {});
      if (r.element) onCapture(r.element);
      else setError("光标下无可拾取元素");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="mt-3 border rounded-lg p-2 bg-violet-50/40">
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold text-violet-700">桌面拾取</p>
        <div className="ml-auto flex gap-1">
          {!spying ? (
            <button onClick={() => void start()}
              className="px-2 py-0.5 text-xs font-medium text-white
                         bg-violet-600 rounded hover:bg-violet-700">
              开始
            </button>
          ) : (
            <>
              <button onClick={capture}
                className="px-2 py-0.5 text-xs font-medium text-white
                           bg-emerald-600 rounded hover:bg-emerald-700">
                捕获
              </button>
              <button onClick={stop}
                className="px-2 py-0.5 text-xs border rounded
                           hover:bg-white">
                停止
              </button>
            </>
          )}
        </div>
      </div>

      {spying && (
        <div className="mt-1 text-[10px] leading-4 font-mono
                        bg-white border border-violet-200 rounded p-1">
          {live ? (
            <>
              <span className="text-violet-600">{live.app_name}</span>
              {" · "}
              <span className="font-semibold">{live.role}</span>
              {live.title ? ` · ${live.title.slice(0, 28)}` : ""}
              {live.bounds && (
                <span className="text-slate-400">
                  {" "}({Math.round(live.bounds.x)},
                  {Math.round(live.bounds.y)}
                  {" · "}
                  {Math.round(live.bounds.w)}×
                  {Math.round(live.bounds.h)})
                </span>
              )}
            </>
          ) : (
            <span className="text-slate-400">移动鼠标到目标元素…</span>
          )}
        </div>
      )}
      {error && <p className="mt-1 text-[10px] text-red-500">{error}</p>}
    </div>
  );
}