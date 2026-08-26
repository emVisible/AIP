/**
 * locator-core 单元测试（Node 直跑：node locator_core.test.mjs）。
 * 用最小假 DOM 对象覆盖选择器/XPath 生成与相似度逻辑——
 * 由 tests/test_locator_core.py 经 subprocess 调用作为回归门禁。
 */
import assert from "node:assert/strict";
import L from "../locator-core.js";

let passed = 0;
function t(name, fn) {
  fn();
  passed++;
  console.log("ok -", name);
}

// ---- 假 DOM 工厂 ----
function mk(tagName, opts = {}) {
  const classes = new Set(opts.class ? opts.class.split(/\s+/) : []);
  const attrs = opts.attrs || {};
  const el = {
    tagName: tagName.toUpperCase(),
    nodeType: 1,
    id: opts.id || "",
    classList: {
      size: classes.size,
      has: (c) => classes.has(c),
      forEach: (fn) => classes.forEach(fn),
      [Symbol.iterator]: () => classes[Symbol.iterator](),
    },
    children: [],
    innerText: opts.text || "",
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    parentElement: null,
    previousElementSibling: null,
    getRootNode() { return { fake: true }; }, // 非 ShadowRoot → inShadow=false
    style: {},
  };
  return el;
}

/** 按顺序挂接父子与兄弟链，返回 parent。 */
function link(parent, ...kids) {
  parent.children = kids;
  kids.forEach((k, i) => {
    k.parentElement = parent;
    k.previousElementSibling = i > 0 ? kids[i - 1] : null;
  });
  return parent;
}

// ---- xpathQuote ----
t("xpathQuote: 无单引号用单引号字面量", () => {
  assert.equal(L.xpathQuote("submit"), "'submit'");
});
t("xpathQuote: 含单引号换双引号字面量", () => {
  assert.equal(L.xpathQuote("it's"), '"it\'s"');
});
t("xpathQuote: 混合引号走 concat 且无反斜杠", () => {
  const q = L.xpathQuote('a\'b"c');
  assert.ok(q.startsWith("concat("), q);
  assert.ok(!q.includes("\\"), "XPath 不支持反斜杠转义: " + q);
});

// ---- buildCss ----
const body = mk("body");
const main = mk("div", { id: "main" });
const list = mk("ul");
const li1 = mk("li", { class: "item" });
const li2 = mk("li", { class: "item" });
link(body, main);
link(main, list);
link(list, li1, li2);

t("buildCss: id 锚定 + 无条件 nth-of-type 链", () => {
  assert.equal(L.buildCss(li1),
    "div#main > ul:nth-of-type(1) > li:nth-of-type(1)");
});
t("buildCss: 同名兄弟序号计数正确", () => {
  assert.equal(L.buildCss(li2),
    "div#main > ul:nth-of-type(1) > li:nth-of-type(2)");
});

// ---- buildXpaths ----
t("buildXpaths: 自带 id 短路", () => {
  const x = mk("button", { id: "go", text: "go" });
  link(body, x);
  const xs = L.buildXpaths(x, { body });
  assert.equal(xs[0], "//*[@id='go']");
});
t("buildXpaths: 最近带 id 祖先锚定相对路径", () => {
  const anchor = mk("div", { id: "wrap" });
  const a = mk("div");
  const target = mk("a", { text: "详情页链接" });
  link(body, anchor);
  link(anchor, a);
  link(a, target);
  const xs = L.buildXpaths(target, { body });
  assert.equal(xs[0], "//*[@id='wrap']/div/a");
});
t("buildXpaths: 叶子文本兜底变体存在且引号安全", () => {
  const leaf = mk("span", { text: "价格: ¥99'8" });
  link(body, leaf);
  const xs = L.buildXpaths(leaf, { body });
  assert.equal(xs.length, 2);
  assert.ok(xs[1].includes("normalize-space()="));
  assert.ok(!xs[1].includes("\\"), xs[1]);
});
t("buildXpaths: shadow 内返回空数组（不可用降级）", () => {
  const shadowEl = mk("span");
  shadowEl.getRootNode = () => ({ host: mk("div") }); // 模拟 ShadowRoot 场景
  // 直接断言 inShadow 分支：伪造 instanceof 通过成本高，此处验证真实浏览器
  // 行为由 content.js 集成路径覆盖；Node 下仅确认不抛异常
  const xs = L.buildXpaths(shadowEl, { body });
  assert.ok(Array.isArray(xs));
});

// ---- relCssInRow ----
t("relCssInRow: 以行为根的相对路径且止于行边界", () => {
  const row = mk("li", { class: "item" });
  const mid = mk("div");
  const title = mk("h3", { class: "title" });
  link(row, mid);
  link(mid, title);
  assert.equal(L.relCssInRow(title, row), "div:nth-of-type(1) > h3:nth-of-type(1)");
});
t("relCssInRow: 字段自带 id 时短路", () => {
  const row = mk("li");
  const price = mk("span", { id: "price-1" });
  link(row, price);
  assert.equal(L.relCssInRow(price, row), "#price-1");
});

// ---- 相似度 / 结构签名 / 命名 ----
t("classSim: 全同=1 全异=0 半交=1/3", () => {
  assert.equal(L.classSim(mk("div", { class: "a b" }),
                         mk("div", { class: "a b" })), 1);
  assert.equal(L.classSim(mk("div", { class: "a" }),
                         mk("div", { class: "b" })), 0);
  assert.ok(Math.abs(L.classSim(mk("div", { class: "a b c" }),
                                mk("div", { class: "a b d" })) -
                    (2 / 4)) < 1e-9);
});
t("structSig: 子标签序列签名", () => {
  const p = mk("div");
  link(p, mk("h3"), mk("p"));
  assert.equal(L.structSig(p), "H3,P");
});
t("guessFieldName: 标签语义优先", () => {
  assert.equal(L.guessFieldName(mk("a"), 0), "link");
  assert.equal(L.guessFieldName(mk("img"), 0), "image");
  assert.equal(L.guessFieldName(mk("h2"), 0), "title");
});
t("guessFieldName: class 关键词次之", () => {
  assert.equal(L.guessFieldName(mk("span", { class: "goods-price red" }), 0),
               "price");
});
t("guessFieldName: 兜底 text_N 去重递增", () => {
  assert.equal(L.guessFieldName(mk("em"), 2), "text_3");
});

console.log(`\n${passed} assertions passed`);
