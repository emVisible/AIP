#!/usr/bin/env node
/**
 * APA 决策引擎正式宿主（R3）—— 驱动纯协议核心 ApaDecisionAgent。
 *
 * 与 cordis_host.mjs 的关系：cordis 用户继续走 index.ts 插件路径；
 * 本宿主零 cordis 依赖，直接消费编译后的 agent 核心 + 可插拔 LLM：
 *   --mock     离线确定性决策（测试/演示）
 *   默认       DeepSeek HTTP（env: DEEPSEEK_API_KEY / DEEPSEEK_MODEL /
 *              DEEPSEEK_BASE_URL）
 *
 * 用法：
 *   node run-agent.mjs --gateway ws://127.0.0.1:8765 --session s_x \
 *     [--source dsh_agent_001] [--actions a.b,c.d] [--think-events e] \
 *     [--max-llm 20] [--mock] [--lifetime-ms N]
 *
 * 退出码：0 = 生命周期正常结束；2 = 参数错误；3 = 连接超时。
 */
import { ApaDecisionAgent } from "./dist/agent.js";

// ---- 参数解析 -----------------------------------------------------------------
function parseArgs(argv) {
  const out = { actions: "human.task.create", source: "dsh_agent_001",
                thinkEvents: [], maxLlm: 20, lifetimeMs: 0, mock: false };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const next = () => argv[++i];
    if (k === "--gateway") out.gateway = next();
    else if (k === "--session") out.session = next();
    else if (k === "--source") out.source = next();
    else if (k === "--tenant") out.tenant = next();
    else if (k === "--actions") out.actions = next();
    else if (k === "--think-events") out.thinkEvents = (next() ?? "").split(",").filter(Boolean);
    else if (k === "--max-llm") out.maxLlm = Number(next());
    else if (k === "--lifetime-ms") out.lifetimeMs = Number(next());
    else if (k === "--mock") out.mock = true;
    else if (k === "--mock-action") out.mockAction = next();
    else if (k === "--mock-target") out.mockTarget = next();
    else { console.error(`unknown arg ${k}`); process.exit(2); }
  }
  if (!out.gateway || !out.session) {
    console.error("usage: node run-agent.mjs --gateway <ws-url> --session <sid> [opts]");
    process.exit(2);
  }
  out.allowedActions = out.actions.split(",").map(s => s.trim()).filter(Boolean);
  return out;
}

const args = parseArgs(process.argv);

// ---- LLM 适配器 ---------------------------------------------------------------

/** DeepSeek OpenAI-compatible chat/completions。 */
class DeepSeekAdapter {
  constructor() {
    this.key = process.env.DEEPSEEK_API_KEY;
    this.model = process.env.DEEPSEEK_MODEL || "deepseek-chat";
    this.base = (process.env.DEEPSEEK_BASE_URL
                 || "https://api.deepseek.com").replace(/\/$/, "");
    if (!this.key) {
      console.error("[llm] DEEPSEEK_API_KEY not set — use --mock or export key");
      process.exit(2);
    }
  }
  async complete(prompt) {
    const resp = await fetch(`${this.base}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 Authorization: `Bearer ${this.key}` },
      body: JSON.stringify({
        model: this.model,
        messages: [{ role: "user", content: prompt }],
        temperature: 0,
      }),
    });
    if (!resp.ok) throw new Error(`deepseek http ${resp.status}`);
    const data = await resp.json();
    return data.choices?.[0]?.message?.content ?? "";
  }
}

/** 离线确定性：固定决策（--mock-action/--mock-target，缺省首个 allowed）。 */
class MockAdapter {
  constructor(cfg) { this.cfg = cfg; }
  async complete(prompt) {
    let action = this.cfg.mockAction;
    if (!action) {
      try {
        const m = prompt.match(/allowed_actions":\s*\[([^\]]*)\]/);
        if (m) action = JSON.parse(`[${m[1]}]`)[0];
      } catch { /* keep undefined */ }
    }
    const decision = this.cfg.mockTarget
      ? { action, params: { target: this.cfg.mockTarget } }
      : { action };
    console.log(`[mock-llm] decide -> ${JSON.stringify(decision)}`);
    return JSON.stringify(decision);
  }
}

const llm = args.mock ? new MockAdapter(args) : new DeepSeekAdapter();

// ---- 启动 agent -----------------------------------------------------------------

const steps = [];
const agent = new ApaDecisionAgent(
  {
    gatewayUrl: args.gateway,
    sessionId: args.session,
    source: args.source,
    tenant: args.tenant,
    allowedActions: args.allowedActions,
    thinkEvents: args.thinkEvents,
    maxLlmDecisions: args.maxLlm,
  },
  llm,
  { onStep: (s) => { steps.push(s); console.log(`[agent] ${s}`); },
    onDone: () => console.log("[agent] done") },
);

console.log(`[run-agent] gateway=${args.gateway} session=${args.session} ` +
            `source=${args.source} llm=${args.mock ? "mock" : "deepseek"}`);
console.log(`[run-agent] allowed=${args.allowedActions.join(",")}`);

// 保活 / 生命周期
if (args.lifetimeMs > 0) {
  setTimeout(() => {
    agent.close();
    process.exit(steps.length ? 0 : 3);
  }, args.lifetimeMs);
}
process.on("SIGINT", () => { agent.close(); process.exit(0); });
process.on("SIGTERM", () => { agent.close(); process.exit(0); });