/**
 * APA 元素拾取器 v2 — 内容脚本（DevTools 级元素提取·交互层）。
 *
 * 依赖 locator-core.js 提供定位器纯函数（window.ApaLocator）。
 * 本文件只负责：事件监听、状态机、UI 渲染、回传编排。
 *
 * 状态机：
 *   idle → picking（悬停检查）
 *   picking --点击重复结构--> list_ctx（整组高亮持久化，点行内元素采字段）
 *   list_ctx --完成提取/Esc--> 回传快照并退出
 */
(() => {
  if (window.__apaPickInstalled) {
    // 重复注入（popup 多次点击）：幂等，等待激活消息即可
    return;
  }
  window.__apaPickInstalled = true;

  const L = window.ApaLocator;

  // ---------- 状态 ----------
  const S = {
    active: false,
    target: null,
    rowCtx: null,   // {rowEl, rows, prevOutlines:Map, rowCss, columns:{}}
  };

  // ---------- UI 宿主（shadow 隔离） ----------
  const host = document.createElement("div");
  host.id = "__apa_pick_host";
  host.style.cssText =
    "all:initial; position:fixed; inset:0; z-index:2147483646; pointer-events:none;";
  const shadow = host.attachShadow({ mode: "open" });
  document.documentElement.appendChild(host);

  const style = document.createElement("style");
  style.textContent = `
    .box{position:fixed;border:2px solid #7c3aed;background:#7c3aed14;
         pointer-events:none;display:none;border-radius:2px;}
    .tag{position:fixed;pointer-events:none;display:none;
         background:#7c3aed;color:#fff;font:600 10px/1.4 ui-monospace,monospace;
         padding:2px 6px;border-radius:4px;white-space:nowrap;z-index:1;}
    .bar{position:fixed;left:0;right:0;bottom:0;display:none;align-items:center;
         gap:4px;padding:5px 10px;background:#0f172aee;color:#e2e8f0;
         font:11px/1.4 ui-monospace,monospace;backdrop-filter:blur(4px);
         pointer-events:auto;z-index:1;}
    .crumb{color:#94a3b8;cursor:pointer;padding:1px 3px;border-radius:3px;
           white-space:nowrap;}
    .crumb:hover{background:#334155;color:#fff;}
    .crumb.on{background:#7c3aed;color:#fff;font-weight:700;}
    .sep{color:#475569;}
    .btn{border:0;border-radius:4px;padding:3px 10px;font:600 11px/1.4
         -apple-system,"PingFang SC",sans-serif;cursor:pointer;margin-left:6px;}
    .btn.done{background:#059669;color:#fff;}
    .btn.exit{background:#334155;color:#cbd5e1;}
    .cnt{margin-left:auto;color:#a78bfa;font-weight:700;white-space:nowrap;}
    .hint{margin-left:8px;color:#64748b;font:10px/1.4 -apple-system,sans-serif;}
  `;
  shadow.appendChild(style);

  const box = document.createElement("div"); box.className = "box";
  const tag = document.createElement("div"); tag.className = "tag";
  const bar = document.createElement("div"); bar.className = "bar";
  shadow.append(box, tag, bar);

  function el(tagName, cls, text) {
    const n = document.createElement(tagName);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // ---------- 列表上下文 ----------
  function enterListCtx(rowEl, rows) {
    const prevOutlines = new Map();
    rows.forEach(r => {
      prevOutlines.set(r, r.style.outline || "");
      r.style.outline = "1px dashed #a78bfa";   // 持久组提示
    });
    S.rowCtx = {
      rowEl, rows, prevOutlines,
      rowCss: L.buildDeepCss(rowEl), columns: {},
    };
    renderBar();
  }

  function exitListCtx() {
    const ctx = S.rowCtx;
    if (ctx) {
      ctx.prevOutlines.forEach((v, r) => { r.style.outline = v; });
      S.rowCtx = null;
    }
    renderBar();
  }

  // ---------- 高亮 / 浮签 / 面包屑 ----------
  function showTarget(el) {
    S.target = el;
    const r = el.getBoundingClientRect();
    box.style.display = "block";
    box.style.left = r.left + "px"; box.style.top = r.top + "px";
    box.style.width = r.width + "px"; box.style.height = r.height + "px";
    tag.style.display = "block";
    const idc = el.id ? "#" + el.id : "";
    const clsc = [...el.classList].slice(0, 2).map(c => "." + c).join("");
    tag.textContent = el.tagName.toLowerCase() + idc + clsc +
      ` · ${Math.round(r.width)}×${Math.round(r.height)}`;
    const tw = tag.offsetWidth, th = tag.offsetHeight;
    tag.style.left = Math.max(2, Math.min(r.left, innerWidth - tw - 4)) + "px";
    tag.style.top = (r.top > th + 6 ? r.top - th - 4 : r.bottom + 4) + "px";
    renderBar();
  }

  function hideTarget() {
    S.target = null;
    box.style.display = "none";
    tag.style.display = "none";
  }

  function renderBar() {
    bar.innerHTML = "";
    bar.style.display = S.active ? "flex" : "none";
    if (!S.active) return;
    const crumbsBox = el("span");
    crumbsBox.style.cssText = "display:flex;gap:4px;overflow-x:auto;";
    bar.appendChild(crumbsBox);

    if (S.target) {
      const chain = [];
      let n = S.target;
      while (n && n !== document.body && n.nodeType === 1) {
        chain.unshift(n);
        n = n.parentElement;
      }
      chain.slice(-6).forEach((node, i, arr) => {
        if (i > 0) crumbsBox.appendChild(el("span", "sep", "›"));
        const lastOne = i === arr.length - 1;
        const c = el("span", "crumb" + (lastOne ? " on" : ""),
          node.tagName.toLowerCase() +
          (node.classList[0] ? "." + node.classList[0] : ""));
        c.title = L.buildCss(node);
        c.onclick = () => showTarget(node);
        crumbsBox.appendChild(c);
      });
    }

    if (S.rowCtx) {
      bar.appendChild(el("span", "cnt",
        "已匹配 " + S.rowCtx.rows.length + " 行 · 字段 " +
        Object.keys(S.rowCtx.columns).length));
      const done = el("button", "btn done", "完成提取");
      done.onclick = finishList;
      bar.appendChild(done);
    } else if (S.target) {
      bar.appendChild(el("span", "hint",
        "点击提取 · 若为列表将自动匹配整组"));
    }
    const quit = el("button", "btn exit", "退出 (Esc)");
    quit.onclick = deactivate;
    bar.appendChild(quit);
  }

  // ---------- 回传 ----------
  function send(payload) {
    try {
      chrome.runtime.sendMessage({ type: "apa-picked", payload });
    } catch (e) { /* 扩展重载中 */ }
  }

  function emitElement(el) {
    const xs = L.buildXpaths(el, document);
    send({
      kind: "element",
      locator: {
        css: L.buildDeepCss(el),
        xpath: xs[0] || null,
        xpath_alt: xs[1] || null,
        in_shadow: L.inShadow(el),
      },
      meta: {
        tag: el.tagName.toLowerCase(),
        text: L.sampleText(el),
        attrs: L.attrSnapshot(el),
        url: location.href.slice(0, 200),
      },
    });
  }

  function emitFieldSnapshot(el) {
    const ctx = S.rowCtx;
    if (!ctx) return;
    let name = L.guessFieldName(el, Object.keys(ctx.columns).length);
    let finalName = name, i = 2;
    while (ctx.columns[finalName]) finalName = name + "_" + i++;
    ctx.columns[finalName] = L.relCssInRow(el, ctx.rowEl);
    send(snapshot(finalName, L.sampleText(el)));
  }

  function snapshot(fieldAdded, sample) {
    const ctx = S.rowCtx;
    return {
      kind: "list",
      row_css: ctx.rowCss,
      match_count: ctx.rows.length,
      columns: { ...ctx.columns },
      field_added: fieldAdded ?? null,
      sample: sample ?? null,
      preview: buildPreview(),
      url: location.href.slice(0, 200),
    };
  }

  function buildPreview() {
    const ctx = S.rowCtx;
    const cols = Object.values(ctx.columns);
    const out = [];
    for (const r of ctx.rows.slice(0, 3)) {
      const vals = [];
      for (const css of cols) {
        let v = "";
        try { v = L.sampleText(r.querySelector(css)); } catch { /* noop */ }
        vals.push(v);
      }
      out.push(vals);
    }
    return out;
  }

  function finishList() {
    const ctx = S.rowCtx;
    if (!ctx) return;
    if (!Object.keys(ctx.columns).length) ctx.columns.text = ":scope";
    send({
      kind: "list_done",
      row_css: ctx.rowCss,
      columns: { ...ctx.columns },
      match_count: ctx.rows.length,
      preview: buildPreview(),
      url: location.href.slice(0, 200),
    });
    exitListCtx();
  }

  // ---------- 相似兄弟检测 ----------
  function findRowSet(el) {
    // L1：同父同标签 ≥2 且 class 相似
    const parent = el.parentElement;
    if (parent) {
      const sibs = [...parent.children]
        .filter(c => c.tagName === el.tagName);
      const sim = sibs.filter(c => L.classSim(c, el) >= 0.5);
      if (sim.length >= 2) return sim;
    }
    // L2：同标签同主类全文档聚类（限 300，校验结构签名一致）
    const cls = [...el.classList][0];
    if (cls) {
      const cand = [...document.querySelectorAll(
        el.tagName.toLowerCase() + "." + CSS.escape(cls))].slice(0, 300);
      const sig = L.structSig(el);
      return cand.filter(c =>
        L.classSim(c, el) >= 0.66 && L.structSig(c) === sig);
    }
    return null;
  }

  // ---------- 事件 ----------
  function onMove(e) {
    if (!S.active) return;
    const t = e.composedPath()[0];
    if (!t || !t.tagName || t === document.documentElement ||
        t === host || host.contains(t)) return;
    if (t === S.target) return;
    showTarget(t);
  }

  function onClick(e) {
    if (!S.active) return;
    const t = e.composedPath()[0];
    if (!t || !t.tagName || host.contains(t)) return;
    e.preventDefault();
    e.stopPropagation();

    if (S.rowCtx) {
      if (t === S.rowCtx.rowEl) return;
      if (S.rowCtx.rows.includes(t)) {
        emitFieldSnapshot(t);          // 行内子元素 → 追加字段
        return;
      }
      exitListCtx();                   // 点击行外 → 退出列表态按单元素处理
    }

    const rows = findRowSet(t);
    if (rows && rows.length >= 2) {
      enterListCtx(t, rows);
      emitFieldSnapshot(t);            // 首个字段即当前点击项
      return;
    }
    emitElement(t);
  }

  function onKey(e) {
    if (e.key === "Escape") deactivate();
  }

  function activate() {
    if (S.active) return;
    S.active = true;
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
    document.documentElement.style.cursor = "crosshair";
    renderBar();
  }

  function deactivate() {
    if (!S.active) return;
    S.active = false;
    exitListCtx();
    hideTarget();
    document.removeEventListener("mousemove", onMove, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKey, true);
    document.documentElement.style.cursor = "";
    bar.style.display = "none";
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg?.type === "apa-pick-start") activate();
    if (msg?.type === "apa-pick-stop") deactivate();
  });

  window.addEventListener("pagehide", () => {
    window.__apaPickInstalled = false;
  });
})();
