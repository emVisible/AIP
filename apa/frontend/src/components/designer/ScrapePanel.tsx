import { useEffect, useRef, useState } from "react";

import { post } from "../../api/client";

interface Status {
  session_id: string;
  pending_picks: number;
  rows_marked: number;
  columns: Record<string, string>;
  row_selector: string;
  strategy: string;
  active: boolean;
  error: string | null;
}

interface PreviewRow {
  [col: string]: string;
}

/**
 * 数据抓取向导面板（影刀数据抓取同款交互）。
 * 输入 URL → 浏览器点两行 → 自动推断行选择器 → 点单元格加列
 * → 预览 → 一键生成 extract_table(+foreach) 步骤入画布。
 */
export function ScrapePanel({ onGenerate }: {
  onGenerate: (steps: unknown[], label: string) => void;
}) {
  const [url, setUrl] = useState("https://");
  const [sid, setSid] = useState("");
  const [st, setSt] = useState<Status | null>(null);
  const [colName, setColName] = useState("");
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [msg, setMsg] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (sid) void post(`/api/scrape/${sid}/stop`, {});
  }, [sid]);

  async function start() {
    setMsg("");
    setPreview(null);
    try {
      const r = await post<{ session_id: string }>("/api/scrape/start",
                                                 { url });
      setSid(r.session_id);
      setMsg("向导浏览器已打开：依次点击【第1行】【第2行】");
      pollRef.current = window.setInterval(async () => {
        try {
          const s = await fetch(`/api/scrape/status/${r.session_id}`)
            .then(x => x.json()) as Status;
          setSt(s);
          if (!s.active) stop();
        } catch { /* ignore */ }
      }, 600);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  function stop() {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (sid) void post(`/api/scrape/${sid}/stop`, {});
    setSid("");
    setSt(null);
  }

  async function assign(role: "row" | "column" | "next") {
    if (!sid) return;
    try {
      const r = await post<{ assigned?: string }>(`/api/scrape/${sid}/assign`,
                                                 { role, name: colName });
      if (role === "row" && st && st.rows_marked >= 2) {
        setMsg(`行选择器已推断 ✓`);
      } else if (r.assigned === "column") {
        setColName("");
      }
      // 立即刷新状态
      const s = await fetch(`/api/scrape/status/${sid}`).then(x => x.json());
      setSt(s as Status);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function doPreview() {
    if (!sid) return;
    try {
      const r = await post<{ rows: PreviewRow[]; count: number }>(
        `/api/scrape/${sid}/preview`, { max_rows: 5 });
      setPreview(r.rows);
      setMsg(`预览 ${r.count} 行 ✓`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  async function generate() {
    if (!sid) return;
    const base = `scrape_${Date.now().toString(36).slice(-4)}`;
    try {
      const r = await post<{ steps: unknown[]; step_count: number }>(
        `/api/scrape/${sid}/generate`,
        { base_id: base, with_loop: false });
      onGenerate(r.steps, `${base}（${r.step_count} 步骤）`);
      setMsg(`已生成 ${r.step_count} 个步骤入画布 ✓`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="mt-3 border rounded-lg p-2 bg-sky-50/40">
      <p className="text-xs font-semibold text-sky-700">📊 数据抓取向导</p>

      {!sid ? (
        <div className="mt-1 flex gap-1">
          <input value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://…"
            className="flex-1 min-w-0 px-2 py-1 text-xs border rounded" />
          <button onClick={() => void start()}
            className="px-2 py-1 text-xs font-medium text-white bg-sky-600
                       rounded hover:bg-sky-700">开始</button>
        </div>
      ) : (
        <>
          <div className="mt-1 text-[10px] font-mono bg-white border
                          border-sky-200 rounded p-1 leading-4">
            <div>行标记: <b>{st?.rows_marked ?? 0}</b>/2
              {st?.row_selector && (
                <> · 选择器:
                  <span className="text-sky-700">{st.row_selector}</span>
                  <span className="text-slate-400"> ({st.strategy})</span>
                </>
              )}
            </div>
            {Object.keys(st?.columns ?? {}).length > 0 && (
              <div>列: {Object.entries(st!.columns).map(([k, v]) => (
                <span key={k} className="mr-1">
                  <b>{k}</b>={v}
                </span>
              ))}</div>
            )}
          </div>

          <div className="mt-1 flex gap-1 flex-wrap">
            {(st?.rows_marked ?? 0) < 2 ? (
              <span className="text-[10px] text-slate-500 py-1">
                请在打开的浏览器中点击第
                {(st?.rows_marked ?? 0) + 1}行…
              </span>
            ) : (
              <>
                <input value={colName}
                  onChange={e => setColName(e.target.value)}
                  placeholder="列名"
                  className="w-16 px-1 py-0.5 text-xs border rounded" />
                <button onClick={() => void assign("column")} disabled={!colName}
                  className="px-2 py-0.5 text-xs border rounded disabled:opacity-40
                             hover:bg-white">
                  +添加列
                </button>
                <button onClick={() => void doPreview()}
                  className="px-2 py-0.5 text-xs border rounded hover:bg-white">
                  预览
                </button>
                <button onClick={() => void generate()}
                  className="ml-auto px-2 py-0.5 text-xs font-medium text-white
                             bg-emerald-600 rounded hover:bg-emerald-700">
                  生成步骤
                </button>
                <button onClick={stop}
                  className="px-2 py-0.5 text-xs border rounded hover:bg-white">
                  关闭
                </button>
              </>
            )}
          </div>

          {preview && preview.length > 0 && (() => {
            const first: PreviewRow = preview[0] ?? {};
            return (
            <table className="mt-1 w-full text-[10px] font-mono border
                              border-slate-200 bg-white">
              <thead>
                <tr className="bg-slate-50">
                  {Object.keys(first).map(k => (
                    <th key={k} className="border-b px-1 text-left">{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.map((row, i) => (
                  <tr key={i}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} className="border-t px-1 truncate max-w-[90px]">
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            );
          })()}
        </>
      )}
      {msg && <p className="mt-1 text-[10px] text-slate-500">{msg}</p>}
    </div>
  );
}