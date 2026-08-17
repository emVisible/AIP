/**
 * AIP Kernel v0.1 — messages (SPEC §3–§6). TypeScript mirror of
 * sdk/python/aip/messages.py and schema/aip.json.
 */
import { randomUUID } from "node:crypto";

export const TYPES = ["event", "action", "result", "error"] as const;
export type MessageType = (typeof TYPES)[number];

export const NON_TERMINAL_STATUS = ["accepted", "running"] as const;
export const TERMINAL_STATUS = ["ok", "failed", "timeout", "rejected"] as const;
export const ALL_STATUS = [...NON_TERMINAL_STATUS, ...TERMINAL_STATUS] as const;
export type ResultStatus = (typeof ALL_STATUS)[number];

export const KERNEL_ERROR_CODES = [
  "INVALID_MESSAGE",
  "INVALID_ACTION",
  "UNSUPPORTED_VERSION",
  "UNAUTHORIZED",
  "SEQ_OUT_OF_ORDER",
  "DUPLICATE_MESSAGE",
  "SESSION_EXPIRED",
  "AGENT_UNAVAILABLE",
  "RPA_UNAVAILABLE",
  "INTERNAL_ERROR",
] as const;
export type ErrorCode = (typeof KERNEL_ERROR_CODES)[number];

export interface Message {
  v: number;
  type: MessageType;
  id: string;
  in_reply_to: string | null;
  session: string;
  seq: number;
  ts: number;
  source: string;
  payload: Record<string, unknown>;
}

export type MessageOptions = Partial<
  Pick<Message, "seq" | "id" | "ts" | "in_reply_to">
>;

export function nowMs(): number {
  return Date.now();
}

export function newId(prefix: string): string {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 12)}`;
}

function base(
  type: MessageType,
  session: string,
  source: string,
  prefix: string,
  opts: MessageOptions,
): Message {
  return {
    v: 1,
    type,
    id: opts.id ?? newId(prefix),
    in_reply_to: opts.in_reply_to ?? null,
    session,
    seq: opts.seq ?? 0, // 0 = unassigned; peers assign the next per-stream value
    ts: opts.ts ?? nowMs(),
    source,
    payload: {},
  };
}

export function makeEvent(
  session: string,
  source: string,
  name: string,
  data?: Record<string, unknown>,
  opts: MessageOptions = {},
): Message {
  const m = base("event", session, source, "evt", opts);
  m.payload = { name, ...(data !== undefined ? { data } : {}) };
  return m;
}

export function makeAction(
  session: string,
  source: string,
  name: string,
  options: {
    target?: string;
    params?: Record<string, unknown>;
    expect?: { event: string };
  } = {},
  opts: MessageOptions = {},
): Message {
  const m = base("action", session, source, "act", opts);
  const payload: Record<string, unknown> = { name };
  if (options.target !== undefined) payload.target = options.target;
  if (options.params !== undefined) payload.params = options.params;
  if (options.expect !== undefined) payload.expect = options.expect;
  m.payload = payload;
  return m;
}

export function makeResult(
  session: string,
  source: string,
  status: ResultStatus,
  inReplyTo: string,
  options: {
    data?: Record<string, unknown>;
    code?: string;
    message?: string;
    duplicate?: boolean;
    originalResultId?: string;
    retry?: { allowed: boolean; after_ms?: number };
  } = {},
  opts: MessageOptions = {},
): Message {
  const m = base("result", session, source, "res", { ...opts, in_reply_to: inReplyTo });
  const payload: Record<string, unknown> = { status };
  if (options.code !== undefined) payload.code = options.code;
  if (options.message !== undefined) payload.message = options.message;
  if (options.data !== undefined) payload.data = options.data;
  if (options.duplicate) payload.duplicate = true;
  if (options.originalResultId !== undefined) payload.original_result_id = options.originalResultId;
  if (options.retry !== undefined) payload.retry = options.retry;
  m.payload = payload;
  return m;
}

export function makeError(
  session: string,
  source: string,
  code: ErrorCode,
  options: {
    message?: string;
    retry?: { allowed: boolean; after_ms?: number };
  } = {},
  opts: MessageOptions = {},
): Message {
  const m = base("error", session, source, "err", opts);
  const payload: Record<string, unknown> = { code };
  if (options.message !== undefined) payload.message = options.message;
  if (options.retry !== undefined) payload.retry = options.retry;
  m.payload = payload;
  return m;
}

export function messageToDict(m: Message): Record<string, unknown> {
  return {
    v: m.v,
    type: m.type,
    id: m.id,
    in_reply_to: m.in_reply_to,
    session: m.session,
    seq: m.seq,
    ts: m.ts,
    source: m.source,
    payload: m.payload,
  };
}

export function messageFromDict(d: Record<string, unknown>): Message {
  return {
    v: (d.v as number) ?? 1,
    type: d.type as MessageType,
    id: (d.id as string) ?? "",
    in_reply_to: (d.in_reply_to as string | null) ?? null,
    session: (d.session as string) ?? "",
    seq: (d.seq as number) ?? 1,
    ts: (d.ts as number) ?? 0,
    source: (d.source as string) ?? "",
    payload: (d.payload as Record<string, unknown>) ?? {},
  };
}

export function validateMessage(m: Message): string[] {
  const errors: string[] = [];
  if (m.v !== 1) errors.push("UNSUPPORTED_VERSION");
  if (!TYPES.includes(m.type)) errors.push("INVALID_MESSAGE: unknown type");
  for (const f of ["v", "type", "id", "session", "seq", "source", "payload"] as const) {
    if (m[f] === undefined || m[f] === null || m[f] === "") errors.push(`INVALID_MESSAGE: missing ${f}`);
  }
  if (m.type === "event" && m.in_reply_to !== null) {
    errors.push("INVALID_MESSAGE: event must not carry in_reply_to");
  }
  if (m.type === "result") {
    if (m.in_reply_to === null) errors.push("INVALID_MESSAGE: result must reference an action id");
    if (!ALL_STATUS.includes(m.payload.status as ResultStatus)) {
      errors.push("INVALID_MESSAGE: unknown result status");
    }
  }
  if (m.type === "error" && !KERNEL_ERROR_CODES.includes(m.payload.code as ErrorCode)) {
    errors.push("INVALID_MESSAGE: unknown error code");
  }
  return errors;
}