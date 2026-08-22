/**
 * 跨语言 E2E 客户端：以 Decision Engine 身份连接 Python WsGatewayServer。
 * 使用与 apa-dsh-plugin 完全相同的协议核心（@aip/protocol 的
 * AIPPeer + WsClientTransport），验证 Python 网关 ↔ TypeScript 对端的
 * 线级兼容性（hello/ping/pong、per-stream seq、事件→动作→结果闭环）。
 *
 * 用法：
 *   node e2e_client.mjs <ws_url> <session> <source> <expect_event> \
 *                       <reply_action> [target]
 *
 * 退出码：0 = 全流程通过；1 = 任一步失败；2 = 参数错误。
 */
import { AIPPeer, WsClientTransport } from "@aip/protocol";

const [url, session, source, expectEvent, replyAction, target] =
  process.argv.slice(2);
if (!url || !session || !source || !expectEvent || !replyAction) {
  console.error("usage: node e2e_client.mjs <ws_url> <session> <source> " +
    "<expect_event> <reply_action> [target]");
  process.exit(2);
}

const steps = [];
const finish = (code) => {
  for (const s of steps) console.log(`[node] ${s}`);
  setTimeout(() => process.exit(code), 50);
};
const fail = (msg) => { steps.push(`FAIL: ${msg}`); finish(1); };

let sawHello = false;
let sawPong = false;
let peer;

const transport = new WsClientTransport(url, {
  onMessage: (m) => onMessage(m),
  onError: (e) => fail(`socket error: ${e.message}`),
});
// 绑定层控制帧走 sendRaw（不消耗 seq，SPEC D1/D4）——与 dsh 插件同款用法
transport.onOpen = () => {
  steps.push("connected");
  transport.sendRaw(JSON.stringify({
    type: "hello", role: "agent", source, cursors: {}, session,
  }));
  transport.sendRaw(JSON.stringify({ type: "ping" }));
};

peer = new AIPPeer(source, session, { transport });

function onMessage(m) {
  // 绑定层帧也经 parseFrame 进入 onMessage；按 payload 特征分流
  const t = m.type;
  if (t === "pong") {
    sawPong = true;
    steps.push("pong received (D4)");
    return;
  }
  if (!sawHello && t === "hello") {
    sawHello = true;
    if (m.session !== session) { fail("hello ack session mismatch"); return; }
    steps.push(`hello ack ok (cursors=${JSON.stringify(m.cursors ?? {})})`);
    return;
  }

  const { kind, message } = peer.handle(m);
  if (kind !== "accept") {
    steps.push(`ignored frame kind=${kind}`);
    return;
  }
  const payload = message.payload ?? {};
  if (message.type === "event" && payload.name === expectEvent) {
    steps.push(`event: ${payload.name} seq=${message.seq}`);
    // DE-3：只带 name/target/params，in_reply_to 关联触发事件
    // （registry schema 校验的是 params.target —— 与 §9.3 一致）
    peer.sendAction(replyAction,
                    { params: target ? { target } : {} },
                    { in_reply_to: message.id });
    steps.push(`action sent: ${replyAction} target=${target}`);
    return;
  }
  if (message.type === "result") {
    const status = payload.status;
    // DE-1：只消费 terminal result；accepted/running 是进度报告
    if (!["ok", "failed", "timeout", "rejected"].includes(status)) {
      steps.push(`progress: ${status}`);
      return;
    }
    if (status !== "ok") {
      fail(`terminal not ok: ${status} ${payload.code ?? ""}`);
      return;
    }
    if (!sawPong) { fail("never received pong"); return; }
    steps.push("terminal ok — cross-language loop closed");
    finish(0);
  }
}

setTimeout(() => fail("timeout after 10s"), 10_000);