/**
 * Cordis glue: mount the APA decision agent inside DeepSeek Harness (dsh).
 *
 * cordis.yml usage (alongside the standard dsh composition):
 *
 *   - id: apa-decision
 *     name: @apa/dsh-plugin
 *     config:
 *       gatewayUrl: ws://127.0.0.1:8765
 *       sessionId: s_po_001
 *       source: dsh_agent_001
 *       allowedActions:
 *         - context.get
 *         - browser.click
 *         - erp.order.approve
 *         - human.task.create
 *
 * The plugin adapts dsh's `llm` service to the minimal LlmLike interface and
 * starts one ApaDecisionAgent. See ./README.md for a full walkthrough.
 */
import type { Context } from "cordis";
import { ApaDecisionAgent, type LlmLike } from "./agent.js";

export const name = "apa-decision";
export const inject = ["llm"];

export interface ApaDecisionPluginConfig {
  gatewayUrl: string;
  sessionId: string;
  source: string;
  allowedActions: string[];
  thinkEvents?: string[];
  maxLlmDecisions?: number;
}

/** Minimal shape of dsh's llm service used here. Adapt if the surface moves. */
interface DshLlmService {
  complete(input: {
    messages: Array<{ role: "system" | "user"; content: string }>;
  }): Promise<{ text?: string; content?: string }> | Promise<string>;
}

function adapt(llm: unknown): LlmLike {
  const svc = llm as DshLlmService;
  return {
    async complete(prompt: string): Promise<string> {
      const out = await svc.complete({
        messages: [{ role: "user", content: prompt }],
      });
      return typeof out === "string" ? out : out.text ?? out.content ?? "";
    },
  };
}

export function apply(ctx: Context, config: ApaDecisionPluginConfig): void {
  const agent = new ApaDecisionAgent(config, adapt(ctx.llm), {
    onStep: (step) => ctx.logger.info("[apa] %s", step),
    onDone: () => ctx.logger.info("[apa] decision engine stopped"),
  });
  ctx.on("dispose", () => agent.close());
}
