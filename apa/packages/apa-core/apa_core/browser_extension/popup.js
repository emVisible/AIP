/** APA 元素拾取器 — popup 逻辑：地址配置 + 激活当前标签页拾取。 */
const baseInput = document.getElementById("base");
const pickBtn = document.getElementById("pick");
const saveBtn = document.getElementById("save");
const statusEl = document.getElementById("status");

chrome.storage.local.get("apaBaseUrl").then(({ apaBaseUrl }) => {
  if (apaBaseUrl) baseInput.value = apaBaseUrl;
});

saveBtn.addEventListener("click", async () => {
  const v = baseInput.value.trim().replace(/\/+$/, "");
  await chrome.storage.local.set({ apaBaseUrl: v });
  statusEl.textContent = "✓ 已保存";
  statusEl.className = "hint ok";
});

pickBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id || !/^https?:/.test(tab.url || "")) {
    statusEl.textContent = "当前页面不支持拾取（仅 http/https）";
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      files: ["locator-core.js", "content.js"],
    });
    await chrome.tabs.sendMessage(tab.id, { type: "apa-pick-start" });
    window.close();
  } catch (e) {
    statusEl.textContent = "注入失败：" + e.message;
  }
});
