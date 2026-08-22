/**
 * 真实 cordis 运行时宿主：以 dsh 同款方式挂载 @apa/dsh-plugin。
 *
 * 与 glue_smoke 的区别：glue 直接调用 apply(ctx mock)；本脚本走完整
 * cordis 容器生命周期 —— Context 创建 → llm 服务提供（Service 基类）→
 * plugin 加载（inject 解析等待就绪）→ apply 注入调用。
 *
 * 用法：node cordis_host.mjs <ws_url> <session> <source> <expect_event> <action> [target]
 */
import { Context, Service } from "cordis";
import * as apaPlugin from "../dist/index.js";

const [url, session, source, expectEvent, action, target] =
  process.argv.slice(2);
if (!url || !session || !source || !expectEvent || !action) {
  console.error(
    "usage: node cordis_host.mjs <url> <session> <source> <event> <action> [target]");
  process.exit(2);
}

// ---- 宿主提供的 llm 服务（模拟 dsh llm 面）----
let decideCalls = 0;

class MockLlmService extends Service {
  static inject = [];
  constructor(ctx) {
    super(ctx, "llm");
  }
  async complete({ messages }) {
    const content =
      messages && messages.length
        ? String(messages[messages.length - 1].content ?? "")
        : "";
    if (!content.includes(expectEvent)) {
      console.error(`[mock-llm] FAIL: prompt missing ${expectEvent}`);
      process.exitCode = 1;
      return "{}";
    }
    decideCalls += 1;
    console.log(`[mock-llm] decision #${decideCalls} for ${expectEvent}`);
    const decision = target ? { action, params: { target } } : { action };
    return `决策：${JSON.stringify(decision)}`;   // 散文包裹 → 验证防御解析
  }
}

// ---- 容器组装 ----
const app = new Context();
app.llm = new MockLlmService(app);          // 属性赋值即服务注册（cordis 惯例）

console.log("[host] cordis context ready, loading apa-decision plugin ...");

// 插件加载：inject ['llm'] 解析等待服务就绪后注入调用 apply(ctx, config)
app.plugin(apaPlugin, {
  gatewayUrl: url,
  sessionId: session,
  source,
  allowedActions: [action],
});

// ---- 保活与自检出口 ----
setTimeout(() => {
  const ok = decideCalls >= 1;
  console.log(`[host] done. llmCalls=${decideCalls}`);
  process.exit(ok ? 0 : 1);
}, 7000);