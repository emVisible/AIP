/**
 * APA Studio Protocol v1 —— GENERATED FILE, DO NOT EDIT.
 *
 * 单源: apa/packages/apa-core/apa_core/studio_protocol.py (pydantic)
 * 再生成: cd apa && python -m apa_core.studio_codegen frontend/src/shared/studioProtocol.ts
 */


export const PROTOCOL_VERSION = 1;

export interface ApprovalElicitation {
  session: string;
  draft_id: string;
  prompt: string;
}

export interface JobRecord {
  id: string;
  kind: string;
  owner_session: string;
  status: "running" | "done" | "cancelled";
  created_at: number;
  settled_at?: number | null;
  result_ref?: string | null;
}

export interface RpcErrorBody {
  code: "method_not_found" | "invalid_params" | "not_found" | "conflict" | "internal_error";
  message: string;
  data?: Record<string, unknown>;
}

export interface RpcRequest {
  id: string;
  method: string;
  params?: Record<string, unknown>;
}

export interface RpcResponse {
  id: string;
  ok: boolean;
  result?: unknown | null;
  error?: RpcErrorBody | null;
}

export interface RunOutcomeNotification {
  session: string;
  outcome: string;
}

export interface RunStepNotification {
  session: string;
  step_id: string;
  action: string;
  status: "ok" | "failed" | "skipped";
  ts: number;
  spilled?: boolean;
}

export interface SessionAppendParams {
  sid: string;
  kind: string;
  payload?: Record<string, unknown>;
}

export interface SessionAppendResult {
  ok: boolean;
  event: SessionEvent;
}

export interface SessionEvent {
  seq: number;
  ts: number;
  kind: string;
  payload: Record<string, unknown>;
}

export interface SessionMeta {
  id: string;
  events: number;
  mtime: number;
  bytes: number;
}

export interface SessionReadResult {
  id: string;
  events: SessionEvent[];
  view: Record<string, unknown>[];
}

