/**
 * APA Desktop — preload 安全桥。
 * 渲染进程（SPA）通过 window.apaDesktop 与主进程通信，
 * 仅暴露拾取器 overlay 所需的最小面。
 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("apaDesktop", {
  /** 显示拾取高亮 overlay（全屏透明窗，忽略鼠标）。 */
  startSpyOverlay: () => ipcRenderer.send("spy-overlay-show"),

  /** 隐藏并销毁 overlay。 */
  stopSpyOverlay: () => ipcRenderer.send("spy-overlay-hide"),

  /** 推送 hover 元素 bounds → overlay 高亮框跟随。 */
  spyBounds: (bounds, label) =>
    ipcRenderer.send("spy-bounds", { bounds, label }),

  /** 拾取会话结束通知（主进程清理 overlay）。 */
  spyEnded: () => ipcRenderer.send("spy-overlay-hide"),
});