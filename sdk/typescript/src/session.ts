/**
 * Action lifecycle and idempotency store (SPEC §6).
 */
import type { ResultStatus } from "./messages.js";

export const RESULT_TO_STATE: Record<ResultStatus, string> = {
  accepted: "ACCEPTED",
  running: "RUNNING",
  ok: "SUCCESS",
  failed: "FAILED",
  timeout: "TIMEOUT",
  rejected: "REJECTED",
};

const TERMINAL = new Set(["SUCCESS", "FAILED", "TIMEOUT", "REJECTED"]);
const TERMINAL_STATUS: ResultStatus[] = ["ok", "failed", "timeout", "rejected"];

export type MarkResult = "ok" | "invalid_status" | "unknown_action" | "after_terminal";

export class ActionStore {
  actions = new Map<string, { state: string; name: string; source: string }>();
  outcomes = new Map<string, [ResultStatus, string | null]>();
  violations: Array<[string, string, string]> = [];

  register(actionId: string, name: string, source: string): void {
    if (!this.actions.has(actionId)) {
      this.actions.set(actionId, { state: "PENDING", name, source });
    }
  }

  mark(actionId: string, status: ResultStatus, resultId?: string): MarkResult {
    const state = RESULT_TO_STATE[status];
    if (!state) return "invalid_status";
    const action = this.actions.get(actionId);
    if (!action) return "unknown_action";
    if (TERMINAL.has(action.state) && !TERMINAL_STATUS.includes(status)) {
      this.violations.push(["I6", actionId, status]);
      return "after_terminal";
    }
    if (status === "accepted" && action.state === "PENDING") {
      action.state = "ACCEPTED";
    } else if (status === "running") {
      action.state = "RUNNING";
    } else {
      action.state = state;
    }
    if (TERMINAL_STATUS.includes(status)) {
      this.outcomes.set(actionId, [status, resultId ?? null]);
    }
    return "ok";
  }

  state(actionId: string): string | undefined {
    return this.actions.get(actionId)?.state;
  }

  outcome(actionId: string): [ResultStatus, string | null] | undefined {
    return this.outcomes.get(actionId);
  }
}

export class Session {
  sessionId: string;
  state: "ACTIVE" | "EXPIRED" = "ACTIVE";
  actions = new ActionStore();
  receiver: import("./sequence.js").Receiver | null = null;

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  cursors(): Record<string, number> {
    return this.receiver ? this.receiver.cursors(this.sessionId) : {};
  }

  expire(): void {
    this.state = "EXPIRED";
  }

  isActive(): boolean {
    return this.state === "ACTIVE";
  }
}