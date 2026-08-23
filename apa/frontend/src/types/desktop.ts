/**
 * Electron preload 暴露的桌面能力（M2 拾取器 overlay）。
 * 纯浏览器环境下不存在 → 使用处全部可选链守卫。
 */
export interface ApaDesktopBridge {
  startSpyOverlay?: () => void;
  stopSpyOverlay?: () => void;
  spyBounds?: (
    bounds: { x: number; y: number; w: number; h: number },
    label: string,
  ) => void;
  spyEnded?: () => void;
}

declare global {
  interface Window {
    apaDesktop?: ApaDesktopBridge;
  }
}

export {};