import { api, post } from "../client";
import type {
  AnalyticsSummary,
  ProcessInfo,
  SessionSummary,
} from "../types";

export const getSessions = () =>
  api<Record<string, SessionSummary>>("/sessions");

export const getAnalytics = () => api<AnalyticsSummary>("/analytics");

export const getProcesses = () => api<ProcessInfo[]>("/processes");

export interface EventDispatchResult {
  dispatched: number;
}

/** 外部事件入口（serve 模式 → Scheduler）*/
export const dispatchEvent = (name: string, data: Record<string, unknown>) =>
  post<EventDispatchResult>("/events", { name, data });
