/**
 * APA 元素拾取器 — 定位器核心（纯函数库）。
 *
 * 双端加载：浏览器经 executeScript 注入（globalThis.ApaLocator），
 * Node 测试经 import（module.exports）。禁止直接依赖 document/window——
 * 全部函数只操作传入的元素引用与标准 DOM 属性接口。
 *
 * 定位策略：
 *   CSS    id 短路 + nth-of-type 链；跨 open shadow root 用 >>> 连接
 *   XPath  @id 精确 → 最近带 id 祖先锚定相对路径 → 文本兜底；
 *          shadow 内不可用（返回空数组，调用方标注降级）
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.ApaLocator = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {

  /** CSS 标识符转义：浏览器走原生 CSS.escape，Node 测试环境用保守回退。 */
  const cssEsc = (s) =>
    (typeof CSS !== "undefined" && CSS.escape)
      ? CSS.escape(s)
      : String(s).replace(/([^a-zA-Z0-9_\u00A0-\uFFFF-])/g, "\\$1");

  /** 文档边界（body）惰性获取；Node 测试环境返回 null 走无文档分支。 */
  function getBody() {
    try {
      return typeof document !== "undefined" ? document.body : null;
    } catch {
      return null;
    }
  }

  function inShadow(el) {
    const root = el.getRootNode?.();
    if (!root || typeof ShadowRoot === "undefined") return false;
    return root instanceof ShadowRoot;
  }

  /** 同父链上同标签序号 step：tag[k]（k>1 或兄弟歧义时带谓词）。 */
  function relStep(n) {
    let k = 1;
    let s = n.previousElementSibling;
    while (s) {
      if (s.tagName === n.tagName) k++;
      s = s.previousElementSibling;
    }
    const sibs = n.parentElement ? n.parentElement.children.length : 1;
    return n.tagName.toLowerCase() + (k > 1 || sibs > 1 ? "[" + k + "]" : "");
  }

  /** CSS 链：向上遇到 id 短路；body/html 边界停止。 */
  function buildCss(el) {
    const parts = [];
    const body = getBody();
    const docEl = typeof document !== "undefined"
      ? document.documentElement : null;
    let node = el;
    while (node && node.nodeType === 1 && node !== body &&
           node !== docEl) {
      if (node.id) {
        parts.unshift(node.tagName.toLowerCase() + "#" +
          cssEsc(node.id));
        break;
      }
      let k = 1;
      let s = node.previousElementSibling;
      while (s) {
        if (s.tagName === node.tagName) k++;
        s = s.previousElementSibling;
      }
      parts.unshift(node.tagName.toLowerCase() + ":nth-of-type(" + k + ")");
      node = node.parentElement;
    }
    if (!parts.length) parts.push(el.tagName.toLowerCase());
    return parts.join(" > ");
  }

  /**
   * 跨 open shadow root 的 CSS：每层 shadow 边界以 host 的 css 为一段，
   * 段间用 >>> 连接（Playwright locator 自动穿透 open root）。
   */
  function buildDeepCss(el) {
    const segs = [];
    let node = el;
    let guard = 0;
    while (node && node.nodeType === 1 && guard++ < 32) {
      segs.unshift(buildCss(node));
      const r = node.getRootNode?.();
      if (r && typeof ShadowRoot !== "undefined" &&
          r instanceof ShadowRoot) {
        node = r.host;
      } else break;
    }
    return segs.join(" >>> ") || el.tagName.toLowerCase();
  }

  /**
   * XPath 字符串字面量安全包装：
   *   无 '  → '…'；无 " → "…"；混合 → concat 片段拼接。
   * （此前版本用反斜杠转义双引号——XPath 不支持，属非法表达式）
   */
  function xpathQuote(s) {
    if (!s.includes("'")) return "'" + s + "'";
    if (!s.includes('"')) return '"' + s + '"';
    const parts = s.split("'").map(p => "'" + p + "'");
    return "concat(" + parts.join(', "\'", ') + ")";
  }

  function relStepPath(el, anchor) {
    const chain = [];
    let n = el;
    while (n && n !== anchor && n.nodeType === 1) {
      chain.unshift(relStep(n));
      n = n.parentElement;
    }
    return chain.join("/");
  }

  /**
   * 候选 XPath 列表（按优先级）：
   *   1. //*[@id='…']                       元素自带 id
   *   2. //*[@id='祖先']/div[2]/a           最近带 id 祖先锚定
   *   3. /html/body/div[1]/…                绝对路径兜底
   *   4. //tag[normalize-space()='文本']     叶子文本定位
   * shadow 内返回 []（XPath 无法穿透）。
   */
  function buildXpaths(el, doc) {
    if (inShadow(el)) return [];
    const out = [];
    if (el.id) {
      out.push("//*[@id=" + xpathQuote(el.id) + "]");
      return out;
    }
    const body = (doc && doc.body) ||
      (typeof document !== "undefined" ? document.body : null);
    let anc = el.parentElement;
    while (anc && anc !== body) {
      if (anc.id) break;
      anc = anc.parentElement;
    }
    if (anc && anc !== body && anc.id) {
      out.push("//*[@id=" + xpathQuote(anc.id) + "]/" +
        relStepPath(el, anc));
    } else if (body) {
      const abs = relStepPath(el, body);
      out.push("/" + body.tagName.toLowerCase() + (abs ? "/" + abs : ""));
    } else {
      out.push("//" + el.tagName.toLowerCase());
    }
    const txt = ((el.innerText ?? "") + "").trim().slice(0, 40);
    if (txt && el.children.length <= 1) {
      out.push("//" + el.tagName.toLowerCase() +
        "[normalize-space()=" + xpathQuote(txt) + "]");
    }
    return out;
  }

  /** 行内字段相对 css：以 rowEl 为根构建子路径。 */
  function relCssInRow(el, rowEl) {
    const parts = [];
    let node = el;
    while (node && node !== rowEl && node.nodeType === 1) {
      if (node.id) {
        parts.unshift("#" + cssEsc(node.id));
        break;
      }
      let k = 1;
      let s = node.previousElementSibling;
      while (s) {
        if (s.tagName === node.tagName) k++;
        s = s.previousElementSibling;
      }
      parts.unshift(node.tagName.toLowerCase() + ":nth-of-type(" + k + ")");
      node = node.parentElement;
    }
    return parts.join(" > ") || el.tagName.toLowerCase();
  }

  /** classList Jaccard 相似度（双方均空视为 1）。 */
  function classSim(a, b) {
    const A = a.classList, B = b.classList;
    if (!A.size && !B.size) return 1;
    let inter = 0;
    A.forEach(x => { if (B.has(x)) inter++; });
    return inter / (A.size + B.size - inter);
  }

  /** 子元素标签签名（结构相似性粗筛）。 */
  function structSig(el) {
    return [...el.children].map(c => c.tagName).join(",");
  }

  /** 字段语义命名：标签优先，其次 class 关键词，最后 text_N 兜底。 */
  function guessFieldName(el, existingCount) {
    const t = el.tagName.toLowerCase();
    if (t === "a") return "link";
    if (t === "img") return "image";
    if (/^h[1-6]$/.test(t)) return "title";
    if (t === "button") return "button";
    if (t === "time") return "time";
    const cls = ([...(el.classList ?? [])].join(" ") || "").toLowerCase();
    const kws = ["price", "title", "name", "date", "time", "desc"];
    for (const kw of kws) {
      if (cls.includes(kw)) return kw;
    }
    return "text_" + ((existingCount || 0) + 1);
  }

  function attrSnapshot(el, keep, cap) {
    const ks = keep || ["id", "class", "name", "href", "type",
                        "aria-label", "placeholder", "title", "role", "alt"];
    const attrs = {};
    for (const k of ks) {
      const v = el.getAttribute?.(k);
      if (v) attrs[k] = String(v).slice(0, cap || 80);
    }
    return attrs;
  }

  function sampleText(el, cap) {
    return ((el.innerText ?? el.value ?? el.getAttribute?.("href") ?? "")
      + "").trim().slice(0, cap || 30);
  }

  return {
    inShadow, buildCss, buildDeepCss, xpathQuote, buildXpaths,
    relCssInRow, classSim, structSig, guessFieldName,
    attrSnapshot, sampleText,
  };
});
