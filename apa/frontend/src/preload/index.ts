/**
 * APA Desktop — preload 安全桥。
 *
 * contextBridge 暴露最小 API 面到渲染进程；
 * 通道名与载荷结构由 src/shared/ipc-types.ts 统一定义。
 */
import { contextBridge, ipcRenderer } from "electron";
import type { ApaDesktopBridge } from "../shared/ipc-types";
import { IpcChannels } from "../shared/ipc-types";

const bridge: ApaDesktopBridge = {
  startSpyOverlay: () => ipcRenderer.send(IpcChannels.SpyOverlayShow),

  stopSpyOverlay: () => ipcRenderer.send(IpcChannels.SpyOverlayHide),

  spyBounds: (bounds, label) =>
    ipcRenderer.send(IpcChannels.SpyBounds, { bounds, label }),

  spyEnded: () => ipcRenderer.send(IpcChannels.SpyOverlayHide),

  registerSpyHotkey: () =>
    ipcRenderer.invoke(IpcChannels.SpyHotkeyRegister) as Promise<string | null>,

  unregisterSpyHotkey: () => ipcRenderer.send(IpcChannels.SpyHotkeyUnregister),

  onSpyCaptureTrigger: (cb) => {
    const listener = () => cb();
    ipcRenderer.on(IpcChannels.SpyCaptureTrigger, listener);
    return () => {
      ipcRenderer.removeListener(IpcChannels.SpyCaptureTrigger, listener);
    };
  },

  openExternal: (url: string) =>
    ipcRenderer.send("os:open-external", url),
};

contextBridge.exposeInMainWorld("apaDesktop", bridge);
