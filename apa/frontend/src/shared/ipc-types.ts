/**
 * IPC 通道常量与跨进程共享类型定义。
 *
 * main / preload / renderer 三端引用此文件，
 * 保证通道名与载荷结构在编译期对齐。
 */

// ---- 通道名枚举 ---------------------------------------------------------------

export const IpcChannels = {
  SpyOverlayShow: "spy-overlay-show",
  SpyOverlayHide: "spy-overlay-hide",
  SpyBounds: "spy-bounds",
} as const;

// ---- 载荷接口 -----------------------------------------------------------------

export interface Bounds {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SpyBoundsPayload {
  bounds: Bounds | null;
  label: string;
}

/** preload 暴露到 renderer 的 apaDesktop 桥面。 */
export interface ApaDesktopBridge {
  startSpyOverlay: () => void;
  stopSpyOverlay: () => void;
  spyBounds: (bounds: Bounds, label: string) => void;
  spyEnded: () => void;
}
