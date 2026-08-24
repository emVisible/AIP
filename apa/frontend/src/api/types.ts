/**
 * API 类型定义 —— 与 Python serve 响应结构镜像（单一权威：后端）。
 * 后端补 OpenAPI spec 后可切换为 openapi-typescript 自动生成。
 */

// ---- 会话 ----
export interface SessionTask {
  task_id: string;
  task_type: string;
}

export interface SessionSummary {
  id: string;
  journal: string;
  state: string;
  cursors: Record<string, number>;
  tasks_open: SessionTask[];
  outcome: string | null;
  last_ts: number;
  tenant?: string | null;
}

// ---- 指标 ----
export interface DurationStats {
  p50: number | null;
  p95: number | null;
}

export interface ActionStats {
  sent: number;
  terminal: number;
  ok: number;
  success_rate: number | null;
  failures_by_risk: Record<string, number>;
  duration_ms: DurationStats;
}

export interface AnalyticsSummary {
  sessions: { total: number; by_state: Record<string, number> };
  actions: ActionStats;
  human_tasks: { open: number; resolved: number };
}

// ---- 流程 ----
export interface ProcessInfo {
  id: string;
  process?: string;
  steps?: number;
  trigger?: string | null;
  valid: boolean;
  error?: string;
}

// ---- 动作目录（registry）----
export interface ActionMeta {
  label_cn?: string;
  description?: string;
  risk: string;
  executor_domain: string;
  idempotency: string;
  params: Record<string, unknown> | null;
  deprecated: boolean;
}

// ---- journal 实时流（SSE）----
export interface JournalRecord {
  kind: string; // state | cursor | action | action_result | task | outcome | error
  ts: number;
  session?: string;
  tenant?: string | null;
  to?: string;
  source?: string;
  seq?: number;
  name?: string;
  status?: string;
  risk?: string;
  verdict?: string;
  duration_ms?: number | null;
  task_id?: string;
  outcome?: string;
}
