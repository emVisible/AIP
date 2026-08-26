/**
 * 浏览器元素拾取面板 —— Chrome 扩展通道（主）/ Playwright 注入（次）。
 *
 * 协议 v2 分流：
 *   kind=element  → 双定位器卡（css/xpath 切换复制）→ 填 target
 *   kind=list     → 列表上下文：匹配数徽标 + 字段 chips（可重命名）
 *                   + 行预览表 → 「生成抓取步骤」产出 extract_table
 *   旧版扁平 payload（tag/text/css）按 element 兼容渲染
 */
import { useEffect, useRef, useState } from "react";

import { post } from "../../api/client";

export interface Locator {
  css: string;
  xpath?: string | null;
  xpath_alt?: string | null;
  in_shadow?: boolean;
}

export interface PickPayload {
  kind?: "element" | "list" | "list_done";
  // element / legacy
  tag?: string;
  text?: string;
  css?: string;
  locator?: Locator;
  meta?: { attrs?: Record<string, string> };
  // list
  row_css?: string;
  columns?: Record<string, string>;
  match_count?: number;
  preview?: string[][];
}

export interface ScrapeSpec {
  row_selector: string;
  columns: Record<string, string>;
  match_count: number;
  /** 附带 foreach 循环步骤（source 预填，循环体在属性面板配置）。 */
  with_loop: boolean;
}

export function BrowserPickPanel({ onPick, onScrapeGenerate,
                                   targetHint }: {
  onPick: (el: PickPayload) => void;
  onScrapeGenerate?: (spec: ScrapeSpec) => void;
  /** 填充模式提示：正在为哪个步骤拾取。 */
  targetHint?: string | null;
}) {
  const [picked, setPicked] = useState<PickPayload | null>(null);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(true);
  const [locatorTab, setLocatorTab] = useState<"css" | "xpath">("css");
  const [names, setNames] = useState<Record<string, string>>({});
  const [withLoop, setWithLoop] = useState(true);
  const [connLost, setConnLost] = useState(false);
  const [lastEvt, setLastEvt] = useState<{ v: number; at: string } | null>(
    null,
  );
  const origin = window.location.origin;

  // 填充模式自动触发：element / list_done 事件到达即回调 onPick（去重防重放）
  const firedRef = useRef(-1);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const failsRef = useRef(0);

  useEffect(() => {
    if (!listening) return;
    let lastVersion = -1;
    const id = setInterval(() => {
      void fetch("/api/browser_pick/result")
        .then((r) => r.json())
        .then((res: { picked: PickPayload | null; version?: number }) => {
          failsRef.current = 0;
          setConnLost(false); // 同值 setState 由 React 跳过，无渲染开销
          const v = res.version ?? 0;
          if (v !== lastVersion) {
            if (lastVersion !== -1 || v > 0) {
              setLastEvt({ v, at: new Date().toLocaleTimeString() });
            }
            lastVersion = v;
            if (res.picked) {
              setPicked(res.picked);
              setNames({});
              setError("");
              const kind = res.picked.kind;
              const autoFillable =
                targetHint != null &&
                (kind === "element" || kind === "list_done" || !kind) &&
                firedRef.current !== v;
              if (autoFillable) {
                firedRef.current = v;
                onPickRef.current(res.picked);
              }
            }
          }
        })
        .catch(() => {
          failsRef.current += 1;
          if (failsRef.current >= 3) setConnLost(true);
        });
    }, 600);
    return () => clearInterval(id);
  }, [listening, targetHint]);

  async function openSandbox() {
    setError("");
    try {
      await post("/api/browser_pick/start",
                 { url: "https://www.baidu.com" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function generate() {
    if (!picked?.kind?.startsWith("list") || !onScrapeGenerate) return;
    const columns: Record<string, string> = {};
    for (const [k, css] of Object.entries(picked.columns ?? {})) {
      columns[names[k] || k] = css;
    }
    onScrapeGenerate({
      row_selector: picked.row_css ?? "",
      columns,
      match_count: picked.match_count ?? 0,
      with_loop: withLoop,
    });
  }

  const isList = !!picked?.kind?.startsWith("list");
  const locator: Locator | undefined =
    picked?.locator ??
    (picked?.css ? { css: picked.css } : undefined);
  const listColumns = picked?.columns ?? {};
  const listPreview = picked?.preview ?? [];

  return (
    <div className="mt-3 border rounded-lg p-2 bg-sky-50/40">
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold text-sky-700">网页拾取</p>
        <span className={`ml-auto text-[10px] px-1 rounded ${
          listening ? "text-emerald-600" : "text-slate-400"}`}>
          {listening ? "● 监听中" : "○ 已暂停"}
        </span>
        <button onClick={() => setListening(o => !o)}
          className="text-[10px] px-1.5 py-0.5 border border-slate-200
                     rounded hover:bg-white">
          {listening ? "暂停" : "恢复"}
        </button>
      </div>

      {/* 联通状态：失败横幅 + 最近事件心跳 */}
      {(connLost || lastEvt) && (
        <div className="mt-1 flex items-center gap-2 text-[9px]">
          {connLost && (
            <span className="rounded bg-red-50 border border-red-100
                             px-1.5 py-0.5 text-red-600">
              后端不可达：确认 APA 服务已启动，且扩展弹窗地址与本面板一致
            </span>
          )}
          {!connLost && lastEvt && (
            <span className="ml-auto font-mono text-slate-300">
              最近事件 v{lastEvt.v} · {lastEvt.at}
            </span>
          )}
        </div>
      )}

      {/* 首次安装引导 */}
      <details className="mt-1.5">
        <summary className="text-[10px] text-sky-600 cursor-pointer
                            select-none hover:text-sky-800">
          首次使用？三步接入你的 Chrome
        </summary>
        <ol className="mt-1 space-y-1 text-[10px] leading-relaxed
                       text-slate-500 list-decimal pl-4">
          <li>
            <a href="/api/browser_pick/extension/download"
               download="apa-picker-extension.zip"
               className="text-blue-500 underline underline-offset-2">
              下载拾取扩展
            </a>{" "}
            并解压
          </li>
          <li>
            Chrome 打开{" "}
            <code className="font-mono bg-white px-0.5 rounded">
              chrome://extensions
            </code>
            ，开启「开发者模式」→「加载已解压的扩展程序」选解压目录
          </li>
          <li>
            扩展弹窗内填入并保存此地址（只需一次）：
            <span className="flex items-center gap-1 mt-0.5">
              <code className="font-mono bg-white border px-1 py-px
                               rounded truncate flex-1">
                {origin}
              </code>
              <button onClick={() =>
                void navigator.clipboard.writeText(origin)}
                className="shrink-0 text-[9px] px-1 py-px border rounded
                           hover:bg-white">
                复制
              </button>
            </span>
            <span className="text-slate-400">
              dev 模式地址固定；打包版应用每次启动端口可能变化，
              失效时回此页复制新地址更新扩展
            </span>
          </li>
        </ol>
      </details>

      <p className="mt-1.5 text-[10px] text-sky-600">
        {targetHint
          ? `填充模式：点选元素即自动写入 ${targetHint}，无需二次确认`
          : "点扩展图标开始拾取：单击提取元素；重复结构自动进入列表模式"}
      </p>

      {/* ===== 列表上下文卡 ===== */}
      {isList && (
        <div className="mt-1 rounded border border-violet-200 bg-white
                        p-1.5 space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="font-semibold text-violet-600">
              列表模式 · 匹配 {picked!.match_count} 行
            </span>
            <span className="text-slate-300 font-mono truncate flex-1">
              {picked!.row_css}
            </span>
          </div>

          {!!Object.keys(listColumns).length && (
            <div className="flex flex-wrap gap-1">
              {Object.entries(listColumns).map(([k, css]) => (
                <span key={k}
                      className="inline-flex items-center gap-0.5
                                 bg-violet-50 rounded px-1 py-px">
                  <input value={names[k] ?? k}
                    onChange={(e) =>
                      setNames(m => ({ ...m, [k]: e.target.value }))}
                    className="w-14 text-[9px] font-mono bg-transparent
                               outline-none border-b border-dotted
                               border-violet-300 focus:border-violet-500"/>
                  <span className="font-mono text-[8px] text-slate-400"
                        title={css}>
                    {css}
                  </span>
                </span>
              ))}
            </div>
          )}

          {!!listPreview.length && (
            <table className="w-full text-[9px] leading-tight">
              <tbody>
                {listPreview.map((row, ri) => (
                  <tr key={ri} className={ri === 0
                    ? "bg-slate-50" : ""}>
                    {row.map((cell, ci) => (
                      <td key={ci}
                          className="border border-slate-100 px-1 py-0.5
                                     max-w-0 truncate text-slate-600">
                        {cell || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {picked!.kind === "list_done" && onScrapeGenerate && (
            <>
              <label className="flex items-center gap-1 text-[9px]
                                text-slate-500 select-none">
                <input type="checkbox" checked={withLoop}
                  onChange={(e) => setWithLoop(e.target.checked)} />
                附带循环遍历（foreach，循环体稍后在属性面板配置）
              </label>
              <button onClick={generate}
                className="w-full py-1 text-[10px] font-medium text-white
                           bg-emerald-600 rounded hover:bg-emerald-700">
                生成抓取步骤（browser.extract_table ·{" "}
                {picked!.match_count} 行）
              </button>
            </>
          )}
          {picked!.kind === "list" && (
            <p className="text-[9px] text-slate-400">
              继续点击行内元素追加字段，或在页面底部条点「完成提取」
            </p>
          )}
        </div>
      )}

      {/* ===== 单元素定位器卡 ===== */}
      {!isList && locator && (
        <div className="mt-1 text-[10px] leading-4 bg-white border
                        border-sky-200 rounded p-1 space-y-1">
          <div className="flex items-center gap-1">
            <span className="font-semibold text-sky-700">
              &lt;{picked!.tag ?? "el"}&gt;
            </span>
            {picked!.text && (
              <span className="text-slate-500 truncate flex-1">
                {picked!.text.slice(0, 28)}
              </span>
            )}
            <button onClick={() => onPick(picked!)}
              className="shrink-0 px-2 py-px text-[10px] font-medium
                         text-white bg-emerald-600 rounded
                         hover:bg-emerald-700">
              使用该元素
            </button>
          </div>
          <div className="flex items-center gap-1">
            {(["css", "xpath"] as const).map(t => (
              <button key={t}
                onClick={() => setLocatorTab(t)}
                disabled={t === "xpath" && !locator.xpath &&
                          !locator.xpath_alt}
                className={`px-1.5 py-px rounded text-[9px] font-mono
                            disabled:opacity-30 ${locatorTab === t
                  ? "bg-sky-600 text-white" : "bg-slate-100"}`}>
                {t}
              </button>
            ))}
            {locator.in_shadow && (
              <span className="text-[8px] text-amber-500">
                shadow DOM · 仅 CSS 可用
              </span>
            )}
            <button onClick={() => void navigator.clipboard.writeText(
              locatorTab === "css"
                ? locator.css
                : locator.xpath ?? locator.css)}
              className="ml-auto text-[9px] px-1 border rounded
                         hover:bg-slate-50">
              复制
            </button>
          </div>
          <p className="font-mono text-[9px] text-slate-400 break-all
                        leading-tight">
            {locatorTab === "css"
              ? locator.css
              : locator.xpath ?? locator.css}
          </p>
        </div>
      )}

      {!isList && !locator && (
        <div className="mt-1 text-[10px] leading-4 bg-white border
                        border-sky-200 rounded p-1 min-h-[36px]">
          <span className="text-slate-400">
            等待你在页面中点选…
          </span>
        </div>
      )}

      {error && <p className="mt-1 text-[10px] text-red-500">{error}</p>}

      {/* 次要入口：无扩展时用 Playwright 沙盒页 */}
      <details className="mt-1">
        <summary className="text-[10px] text-slate-300 cursor-pointer
                            select-none hover:text-slate-500">
          没装扩展？用内置浏览器打开一个新页面拾取
        </summary>
        <button onClick={() => void openSandbox()}
          className="mt-1 w-full py-1 text-[10px] border border-sky-200
                     text-sky-600 rounded hover:bg-white">
          打开沙盒页（百度首页）
        </button>
      </details>
    </div>
  );
}
