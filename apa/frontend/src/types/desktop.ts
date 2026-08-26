/**
 * Electron preload 暴露的桌面能力（Window 全局类型增强）。
 *
 * 单一真相源为 shared/ipc-types.ts 的 ApaDesktopBridge；
 * 此处仅做「全部可选」投影——纯浏览器环境下 window.apaDesktop
 * 不存在 → 使用处全部可选链守卫。
 */
import type { ApaDesktopBridge as IpcDesktopBridge }
  from "../shared/ipc-types";

export type ApaDesktopBridge = Partial<IpcDesktopBridge>;

declare global {
  interface Window {
    apaDesktop?: ApaDesktopBridge;
  }
}

export {};
