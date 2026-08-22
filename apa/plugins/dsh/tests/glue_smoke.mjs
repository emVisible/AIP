/**
 * 胶水层运行时冒烟：经编译产物 dist/index.js 的 apply() 入口，
 * 以最小 ctx（脚本化 llm）连接 Python WsGatewayServer 完成一次决策闭环。
 * Python 侧断言动作真实执行；本脚本 4 秒后自动退出。
 *
 * 用法：node glue_smoke.mjs <ws_url> <session> <source> <expect_event> <action> [target]
 */
import { apply } from "../dist/index.js";

const [url, session, source, expectEvent, action, target] = process.argv.slice(2);
if (!url) {
  console.error("usage: node glue_smoke.mjs <url> <session> <source> <event> <action> [target]");
  process.exit(2);
}

const ctx = {
  llm: {
    // dsh 服务形状：complete({messages}) —— 经插件 adapt() 包装后到达此处
    async complete({ messages }) {
      const content = messages[messages.length - 1].content ?? "";
      if (!content.includes(expectEvent)) {
        console.error("[node] FAIL: prompt missing expected event");
        process.exit(1);
      }
      console.log(`[node] llm deciding for ${expectEvent}`);
      const decision = target
        ? { action, params: { target } }
        : { action };
      return `决策：${JSON.stringify(decision)}`;   // 散文包裹 → 验证防御性解析
    },
  },
  logger: { info: (...a) => console.log("[apa]", ...a) },
  on(_event, _cb) {},
};

apply(ctx, {
  gatewayUrl: url,
  sessionId: session,
  source,
  allowedActions: [action],
});

setTimeout(() => process.exit(0), 4000);   // 留足闭环时间