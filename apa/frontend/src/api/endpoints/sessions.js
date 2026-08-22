import { api, post } from "../client";
export const getSessions = () => api("/sessions");
export const getAnalytics = () => api("/analytics");
export const getProcesses = () => api("/processes");
export const getRegistryActions = () => api("/registry/actions");
/** 外部事件入口（serve 模式 → Scheduler）*/
export const dispatchEvent = (name, data) => post("/events", { name, data });
