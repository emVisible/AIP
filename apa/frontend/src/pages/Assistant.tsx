import { useEffect, useState } from "react";

interface AiStatus {
  mode: string;
  model: string;
  key_configured: boolean;
}

export function Assistant() {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/api/ai/status")
      .then(r => r.json())
      .then(d => { setStatus(d); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, []);

  return (
    <div className="space-y-4 max-w-2xl">
      <h1 className="text-xl font-bold">AI 助手</h1>

      {!loaded ? (
        <p className="text-sm text-slate-400">加载中…</p>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-surface p-5
                        space-y-3">
          <h2 className="text-sm font-semibold">决策引擎配置状态</h2>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">模式</dt>
              <dd className="font-medium">{status?.mode ?? "rules_only"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">模型</dt>
              <dd className="font-mono text-xs">{status?.model ?? "deepseek-chat"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">API Key</dt>
              <dd>
                {status?.key_configured
                  ? <span className="text-emerald-600">✓ 已配置</span>
                  : <span className="text-amber-500">✗ 未配置</span>}
              </dd>
            </div>
          </dl>

          {!status?.key_configured && (
            <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200
                            space-y-1">
              <p className="text-xs font-semibold text-amber-700">
                启用 LLM 决策级联（§7.2 L1/L2）</p>
              <p className="text-xs text-amber-600 leading-relaxed">
                编辑仓库根目录的 <code className="font-mono bg-amber-100 px-1 rounded">.env</code> 文件：
                <br />DEEPSEEK_API_KEY=sk-your-key-here
                <br />然后重启 APA Desktop 即可启用真实 LLM 决策。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}