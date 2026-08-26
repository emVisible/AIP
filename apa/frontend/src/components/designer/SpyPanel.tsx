/**
 * 桌面拾取面板（纯展示）—— 会话状态由 useDesktopSpy 提供。
 * 展示 hover 元素实时信息；开始/捕获/停止按钮直连 hook 动作。
 */
import type { CapturedElement, SpyElement,
              useDesktopSpy } from "../../hooks/useDesktopSpy";

type Spy = ReturnType<typeof useDesktopSpy>;

export type { CapturedElement };

export function SpyPanel({ spy, targetHint }: {
  spy: Spy;
  /** 填充模式提示：正在为哪个步骤拾取。 */
  targetHint?: string | null;
}) {
  const { spying, live, error, start, stop, capture } = spy;
  return (
    <div className="mt-3 border rounded-lg p-2 bg-violet-50/40">
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold text-violet-700">桌面拾取</p>
        <div className="ml-auto flex gap-1">
          {!spying ? (
            <button onClick={start}
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
        <p className="mt-1 text-[10px] text-violet-500">
          {targetHint
            ? `填充模式：捕获结果将写入 ${targetHint}`
            : "移动鼠标到目标元素，捕获后插入点击步骤"}
          {spy.hotkey && (
            <span className="ml-1 font-semibold">
              （按 {spy.hotkey} 快速捕获）
            </span>
          )}
        </p>
      )}

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
      {error && (
        <div className="mt-1 text-[10px] leading-4 rounded p-1.5
                        bg-red-50 border border-red-100">
          <p className="text-red-600">{error}</p>
          {/辅助功能|权限/.test(error) && (
            <button
              onClick={() => window.apaDesktop?.openExternal?.(
                "x-apple.systempreferences:" +
                "com.apple.preference.security?Privacy_Accessibility")}
              className="mt-1 px-2 py-0.5 text-[10px] font-medium
                         text-white bg-red-500 rounded hover:bg-red-600">
              打开系统设置 · 辅助功能
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** 兼容旧引用（DesignerPage 类型标注用）。 */
export type SpyLiveElement = SpyElement;
