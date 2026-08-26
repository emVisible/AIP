/**
 * 桌面元素拾取会话（受控 hook）—— 影刀式 Ctrl 悬停体验的状态封装。
 *
 * 职责：/api/spy/start·stream·capture·stop 的生命周期 + SSE hover 帧 +
 * Electron overlay 高亮联动。UI 无关；SpyPanel 与属性面板的「从屏幕
 * 拾取」共用同一实例。
 */
import { useEffect, useRef, useState } from "react";

import { post } from "../api/client";

/** SpyService hover 帧。 */
interface HoverFrame {
  type: string;
  version?: number;
  element?: SpyElement | null;
}

export interface SpyElement {
  role: string;
  title: string;
  value: string | null;
  app_name: string;
  pid: number;
  bounds: { x: number; y: number; w: number; h: number } | null;
}

/** /api/spy/capture 返回的完整可回放描述符。 */
export interface CapturedElement extends SpyElement {
  ax_path: unknown[];
}

export function useDesktopSpy(onCapture: (el: CapturedElement) => void): {
  spying: boolean;
  live: SpyElement | null;
  error: string;
  /** 全局捕获快捷键实际生效键位（F2/F6）；null = 未注册或非 Electron。 */
  hotkey: string | null;
  start: () => void;
  stop: () => void;
  capture: () => void;
} {
  const [spying, setSpying] = useState(false);
  const [live, setLive] = useState<SpyElement | null>(null);
  const [error, setError] = useState("");
  const [hotkey, setHotkey] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // 回调经 ref 取最新值，避免 SSE/快捷键长连接闭包过期
  const captureCbRef = useRef(onCapture);
  captureCbRef.current = onCapture;
  const captureRef = useRef<() => void>(() => {});
  const triggerDisposerRef = useRef<(() => void) | null>(null);

  function cleanup() {
    esRef.current?.close();
    esRef.current = null;
    triggerDisposerRef.current?.();
    triggerDisposerRef.current = null;
    window.apaDesktop?.unregisterSpyHotkey?.();
    setHotkey(null);
    window.apaDesktop?.stopSpyOverlay?.();
  }

  // 卸载兜底：断流 + 停服务端会话
  useEffect(() => () => {
    if (esRef.current) {
      esRef.current.close();
      void post("/api/spy/stop", {});
    }
  }, []);

  /** 已知后端错误文案 → 中文指引（其余原样透出）。 */
  const ERR_ZH: [RegExp, string][] = [
    [/spy not started/i, "拾取会话未启动，请先点「开始」"],
    [/nothing under cursor/i, "光标下无可拾取元素，先移动鼠标悬停到目标上"],
  ];

  function errText(e: unknown): string {
    const raw = e instanceof Error
      ? ((e as { detail?: string }).detail || e.message)
      : String(e);
    for (const [re, zh] of ERR_ZH) {
      if (re.test(raw)) return zh;
    }
    return raw;
  }

  function start(): void {
    setError("");
    void (async () => {
      try {
        await post("/api/spy/start", {});
      } catch (e) {
        // 权限预检 409 等：直接呈现后端指引，不进入会话
        setSpying(false);
        setError(errText(e));
        return;
      }
      setSpying(true);
      setLive(null);
      window.apaDesktop?.startSpyOverlay?.();

        const es = new EventSource("/api/spy/stream");
        esRef.current = es;
        es.onmessage = (ev) => {
          try {
            const frame: HoverFrame & { message?: string } =
              JSON.parse(ev.data);
            if (frame.type === "hover") {
              setLive(frame.element ?? null);
              const b = frame.element?.bounds;
              if (b && b.w > 0) {
                const el = frame.element!;
                window.apaDesktop?.spyBounds?.(b,
                  `${el.app_name} · ${el.role}` +
                  (el.title ? ` · ${el.title.slice(0, 30)}` : ""));
              }
            } else if (frame.type === "error") {
              // EventTap 线程失败（典型：辅助功能权限缺失）——明确报错并结束会话
              setError(frame.message ?? "拾取会话异常");
              stop();
            } else if (frame.type === "ended" || frame.type === "timeout") {
              stop();
            }
          } catch { /* 忽略坏帧 */ }
        };
        es.onerror = () => { /* 断线由 stop 兜底 */ };

        // 全局捕获快捷键（Electron 环境；纯浏览器环境静默跳过）
        triggerDisposerRef.current =
          window.apaDesktop?.onSpyCaptureTrigger?.(
            () => captureRef.current()) ?? null;
        void window.apaDesktop?.registerSpyHotkey?.()
          .then((acc) => setHotkey(acc ?? null))
          .catch(() => setHotkey(null));
    })();
  }

  function stop(): void {
    cleanup();
    setSpying(false);
    void post("/api/spy/stop", {});
  }

  function capture(): void {
    void (async () => {
      try {
        const r = await post<{ element?: CapturedElement }>(
          "/api/spy/capture", {});
        if (r.element) captureCbRef.current(r.element);
        else setError("光标下无可拾取元素");
      } catch (e) {
        setError(errText(e));
      }
    })();
  }

  captureRef.current = capture;

  return { spying, live, error, hotkey, start, stop, capture };
}
