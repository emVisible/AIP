/**
 * Action Registry profile (SPEC §9.3). Idempotency / timeout / retries are
 * Registry properties, never per-call parameters on the action message.
 */
export type Idempotency = "required" | "optional" | "none";

export interface ActionDef {
  name: string;
  idempotency: Idempotency;
  timeoutMs: number;
  retries: number;
  risk?: string;
}

export class ActionRegistry {
  private defs = new Map<string, ActionDef>();

  register(
    name: string,
    options: { idempotency?: Idempotency; timeoutMs?: number; retries?: number; risk?: string } = {},
  ): this {
    this.defs.set(name, {
      name,
      idempotency: options.idempotency ?? "none",
      timeoutMs: options.timeoutMs ?? 0,
      retries: options.retries ?? 0,
      risk: options.risk,
    });
    return this;
  }

  get(name: string): ActionDef | undefined {
    return this.defs.get(name);
  }

  has(name: string): boolean {
    return this.defs.has(name);
  }
}