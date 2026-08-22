/**
 * APA decision-engine agent (protocol core).
 *
 * Pure logic against @aip/protocol only — no cordis/dsh imports here, so the
 * decision loop is unit-testable without the harness. The cordis glue in
 * `index.ts` adapts dsh's llm service to the `LlmLike` interface.
 *
 * Design doc: APA_Design_Document_v2.md §7.3. Contract (§7.1):
 *   DE-1 only terminal results drive business decisions
 *   DE-2 fetch context on demand via context.get; never cache session state
 *   DE-3 actions carry name/target/params only
 *   DE-5 when uncertain, create a human.task instead of guessing
 */
import { AIPPeer, Message, WsClientTransport } from "@aip/protocol";

export interface LlmLike {
  /** One-shot completion returning raw assistant text. */
  complete(prompt: string): Promise<string>;
}

export interface ApaDecisionConfig {
  gatewayUrl: string;
  sessionId: string;
  source: string;
  allowedActions: string[];
  /** Events routed with deeper reasoning (L2). Default: none. */
  thinkEvents?: string[];
  maxLlmDecisions?: number;
}

interface Decision {
  action?: string;
  target?: string;
  params?: Record<string, unknown>;
  uncertain?: string;
}

const SYSTEM_PROMPT = `You are the decision engine of an enterprise RPA system (APA).
You receive ONE semantic event and must output exactly one decision.
Output ONLY a single JSON object:
  {"action": "<name>", "target"?: "...", "params"?: {...}}
or {"uncertain": "<reason>"} when you cannot decide safely.
Choose action ONLY from allowed_actions. Never include idempotency or risk.`;

export function parseDecision(text: string): Decision {
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) return { uncertain: "no_json" };
  try {
    const obj = JSON.parse(m[0]) as Record<string, unknown>;
    if (typeof obj !== "object" || obj === null) return { uncertain: "not_object" };
    if ("uncertain" in obj) return { uncertain: String(obj.uncertain).slice(0, 200) };
    if (typeof obj.action !== "string" || !obj.action)
      return { uncertain: "missing_action" };
    const params = (obj.params ?? {}) as Record<string, unknown>;
    if (typeof params !== "object") return { uncertain: "bad_params" };
    const out: Decision = { action: obj.action, params };
    if (typeof obj.target === "string" && obj.target) out.target = obj.target;
    return out;
  } catch {
    return { uncertain: "bad_json" };
  }
}

export class ApaDecisionAgent {
  readonly peer: AIPPeer;
  private transport: WsClientTransport & { sendRaw?: (t: string) => void };
  private pendingContext = new Map<string, (d: unknown) => void>();
  private llmBudget: number;
  readonly stats = { L1: 0, L2: 0, human: 0 };

  constructor(
    private config: ApaDecisionConfig,
    private llm: LlmLike,
    private hooks: {
      onStep?: (step: string) => void;
      onDone?: () => void;
    } = {},
  ) {
    this.llmBudget = config.maxLlmDecisions ?? 20;
    this.transport = new WsClientTransport(config.gatewayUrl, {
      onMessage: (m) => this.onMessage(m),
      onError: (e) => this.hooks.onStep?.(`transport error: ${e.message}`),
    }) as WsClientTransport & { sendRaw?: (t: string) => void };
    this.peer = new AIPPeer(config.source, config.sessionId, { transport: this.transport });
    // Binding-level hello (never consumes seq — SPEC D4/D1).
    const open = () => {
      this.transport.sendRaw?.(JSON.stringify({
        type: "hello", role: "agent", source: config.source,
        cursors: {}, session: config.sessionId,
      }));
    };
    if ("sendRaw" in this.transport && typeof this.transport.sendRaw === "function") {
      // onOpen fires before messages once wired by the transport.
      (this.transport as unknown as { onOpen?: () => void }).onOpen = open;
    }
  }

  close(): void {
    this.transport.close();
  }

  private onMessage(m: Message): void {
    const { kind, message } = this.peer.handle(m);
    if (kind !== "accept") return; // duplicate/stale/gap handled upstream
    if (message.type === "event") void this.decide(message);
    else if (message.type === "result") this.onResult(message);
  }

  /** Event → one decision (L1 fast / L2 deep). */
  private async decide(m: Message): Promise<void> {
    const payload = m.payload as { name?: string; data?: Record<string, unknown> };
    const name = payload.name ?? "";
    const data = payload.data ?? {};
    if (this.stats.L1 + this.stats.L2 + this.stats.human >= this.llmBudget) return;

    const level = this.config.thinkEvents?.includes(name) ? "L2" : "L1";
    const prompt = JSON.stringify({
      event: name,
      data,
      allowed_actions: this.config.allowedActions,
    });
    let decision: Decision;
    try {
      decision = parseDecision(await this.llm.complete(
        `${SYSTEM_PROMPT}\n\n${prompt}`));
    } catch (e) {
      decision = { uncertain: `llm_error:${String(e).slice(0, 80)}` };
    }

    if (decision.action && this.config.allowedActions.includes(decision.action)) {
      this.stats[level] += 1;
      this.hooks.onStep?.(`cascade[${level}]: ${decision.action}`);
      // DE-3: name/target/params only — idempotency/risk live in the Registry.
      this.peer.sendAction(decision.action, {
        target: decision.target,
        params: decision.params,
      }, { in_reply_to: m.id });
      return;
    }

    // DE-5: uncertain or out-of-list action → human escalation.
    this.stats.human += 1;
    const reason = decision.uncertain ?? `action_not_allowed:${decision.action}`;
    this.hooks.onStep?.(`cascade[${level}]: uncertain (${reason}) → human.task`);
    this.peer.sendAction("human.task.create", {
      params: {
        task_type: "exception",
        assignee_role: "rpa_operator",
        context_ref: String((data as Record<string, unknown>).context ?? ""),
        available_outcomes: ["retry", "skip", "abort"],
      },
    }, { in_reply_to: m.id });
  }

  /** DE-1: only terminal results matter; context.get replies resolve waiters. */
  private onResult(m: Message): void {
    const status = (m.payload as { status?: string }).status ?? "";
    const replyTo = m.in_reply_to ?? "";
    const waiter = this.pendingContext.get(replyTo);
    if (waiter) {
      this.pendingContext.delete(replyTo);
      waiter((m.payload as { data?: unknown }).data);
      return;
    }
    if (status === "rejected") {
      this.hooks.onStep?.(`result: rejected (${String(
        (m.payload as { code?: string }).code)}) — stop`);
      this.hooks.onDone?.();
    }
  }

  /** DE-2: Context-on-Demand fetch through the standard action path. */
  contextGet(ref: string, fields: string[]): Promise<unknown> {
    const msg = this.peer.sendAction("context.get", { params: { ref, fields } });
    return new Promise((resolve) => this.pendingContext.set(msg.id, resolve));
  }
}