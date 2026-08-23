// APA Desktop preload —— 最小 contextBridge 暴露。
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("apaDesktop", {
  version: process.versions.electron,
  platform: process.platform,
});