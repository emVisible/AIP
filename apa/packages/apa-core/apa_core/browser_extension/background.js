/**
 * APA 元素拾取器 — Service Worker。
 *
 * 职责：接收内容脚本的选取结果 → POST 到用户配置的 APA 服务地址；
 * 快捷键（Alt+Shift+P）触发当前标签页注入并激活拾取。
 * APA 地址存 chrome.storage.local（key: apaBaseUrl），由 popup 配置。
 */

const DEFAULT_TIMEOUT_MS = 4000;

async function getBaseUrl() {
  const { apaBaseUrl } = await chrome.storage.local.get("apaBaseUrl");
  return (apaBaseUrl || "").replace(/\/+$/, "");
}

async function forwardToApa(payload) {
  const base = await getBaseUrl();
  if (!base) {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setTitle({ title: "未配置 APA 地址：点击扩展图标完成设置" });
    return;
  }
  try {
    const r = await fetch(base + "/api/browser_pick/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
    if (r.ok) {
      chrome.action.setBadgeText({ text: "" });
    } else {
      chrome.action.setBadgeText({ text: String(r.status) });
    }
  } catch (e) {
    chrome.action.setBadgeText({ text: "x" });
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
  if (msg && msg.type === "apa-picked" && msg.payload) {
    forwardToApa(msg.payload);
  }
});

/** 快捷键 / 后续入口：向当前标签页注入 content.js 并激活拾取。 */
async function startPickInActiveTab() {
  const [tab] = await chrome.tabs.query(
    { active: true, currentWindow: true });
  if (!tab || !tab.id ||
      !/^https?:/.test(tab.url || "")) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      files: ["locator-core.js", "content.js"],
    });
    await chrome.tabs.sendMessage(tab.id, { type: "apa-pick-start" });
  } catch (e) {
    /* 受限页面（chrome:// 等）静默 */
  }
}

chrome.commands.onCommand.addListener((command) => {
  if (command === "start-pick") void startPickInActiveTab();
});
