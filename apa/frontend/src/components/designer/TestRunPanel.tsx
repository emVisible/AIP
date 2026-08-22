import { useState } from "react";
import { api } from "../../api/client";

/** 沙盒试运行面板 —— 职责单一：输入事件+数据 → 展示步骤轨迹。 */
export function TestRunPanel({ yaml }: { yaml: string }) {
  const [ev, setEv] = useState("");
  const [data, setData] = useState("{}");
  interface TestStep { id?: string; action?: string; status?: string; result?: Record<string, unknown> }
  interface TestResult {
    outcome: string;
    gateway_state: string;
    steps: TestStep[];
    error?: string;
  }
  const [result, setResult] = useState<TestResult | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    try {
      const d = await api<TestResult>("/api/processes/test", {
        method: "POST",
        body: JSON.stringify({ yaml, event: ev, data: JSON.parse(data || "{}") }),
      });
      setResult(d);
    } catch (e) {
      setResult({ outcome: "error", gateway_state: "", steps: [],
                  error: String(e) });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-2 p-1">
      <p className="text-[10px] font-semibold text-slate-400 uppercase">
        沙盒试运行（MockERP）
      </p>
      <input
        className="w-full px-2 py-1 text-xs border rounded"
        placeholder="触发事件名"
        value={ev}
        onChange={(e) => setEv(e.target.value)}
      />
      <textarea
        className="w-full px-2 py-1 text-xs font-mono border rounded resize-y"
        rows={3}
        placeholder="{}"
        value={data}
        onChange={(e) => setData(e.target.value)}
      />
      <button
        className="w-full py-1.5 text-xs font-semibold text-white bg-brand
                   rounded hover:bg-blue-700 disabled:opacity-50"
        disabled={running}
        onClick={run}
      >{running ? "运行中…" : "▶ 试运行"}</button>
      {result != null && (
        <pre className="text-[11px] bg-slate-900 text-green-300 p-2 rounded
                        overflow-x-auto max-h-[240px]">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}