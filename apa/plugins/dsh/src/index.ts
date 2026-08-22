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
 *         - human.task.create
 *
 * The plugin adapts dsh's `llm` service to the minimal LlmLike interface and
 * starts one ApaDecisionAgent. See ./README.md for a full walkthrough.
 *
 * 类型策略：不 import cordis 的命名导出（4.0 rc 的 d.ts 存在 TS2694 发布缺陷，
 * 见 git history）。cordis 运行时只要求本包导出 name/inject/apply —— 用结构化
 * 最小上下文类型即可获得完整 DX 与运行时正确性。
 */
import { ApaDecisionAgent, type LlmLike } from "./agent.js";

export const name = "apa-decision";
export const inject = ["llm"];

export interface ApaPluginConfig {
  gatewayUrl: string;
  sessionId: string;
  source: string;
  allowedActions: string[];
  /** 走 L2 深度推理的事件名集合 */
  thinkEvents?: string[];
  /** 单会话 LLM 决策预算（防失控），默认 20 */
  maxLlmDecisions?: number;
}

/** dsh `llm` 服务被使用到的最小形状（演进时只需调整 adapt）。 */
interface DshLlmService {
  complete(input: {
    messages: Array<{ role: "system" | "user"; content: string }>;
  }): Promise<{ text?: string; content?: string } | string>;
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

/** cordis Context 的结构化最小面（避免依赖 rc 版命名导出）。 */
interface MinimalCtx {
  llm: unknown;
  logger: { info: (...args: unknown[]) => void };
  on(event: string, cb: () => void): void;
}

export function apply(ctx: MinimalCtx, config: ApaPluginConfig): void {
  const agent = new ApaDecisionAgent(config, adapt(ctx.llm), {
    onStep: (step) => ctx.logger.info("[apa] %s", step),
    onDone: () => ctx.logger.info("[apa] decision engine stopped"),
  });
  ctx.on("dispose", () => agent.close());
}