/**
 * AI 配置设置卡（H7b）—— LLM / 审批 / 沙箱 / 外部 MCP 服务器。
 *
 * 数据流：useSettings 的 redacted 视图 → 本地 draft → 保存时整段 patch
 * 提交 settings.update。env-owned 字段自动只读并标注来源；
 * auth_spec 仅支持引用（env 变量名 / vault 名称），明文永不经过 UI。
 */
import { useState } from "react";

import { getIn, isEnvOwned, useSettings } from "../../hooks/useSettings";
import { Button, Card, CardHeader } from "../ui";

type SaveFn = (patch: Record<string, any>) => Promise<string | null>;

/** 通用受控字段：值来自 view，env-owned 时只读。 */
function Field({ label, hint, value, onChange, owned,
                  type = "text", options }: {
  label: string;
  hint?: string;
  value: string | number | undefined;
  onChange: (v: string) => void;
  owned: boolean;
  type?: "text" | "number";
  options?: string[];
}) {
  return (
    <label className="block space-y-1">
      <span className="flex items-baseline gap-2">
        <span className="text-xs font-medium text-slate-600">{label}</span>
        {hint && <span className="text-[10px] text-slate-400">{hint}</span>}
        {owned && (
          <span className="text-[9px] rounded bg-amber-50 text-amber-600
                           px-1">🔒 环境变量管理</span>
        )}
      </span>
      {options ? (
        <select disabled={owned} value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full h-8 px-2 text-xs border rounded-md outline-none
                      ${owned ? "bg-slate-50 text-slate-400"
                              : "bg-white border-slate-200 focus:border-blue-400"}`}>
          <option value="">— 选择 —</option>
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input type={type} disabled={owned} value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full h-8 px-2 text-xs border rounded-md outline-none
                      ${owned ? "bg-slate-50 text-slate-400"
                              : "bg-white border-slate-200 focus:border-blue-400"}`} />
      )}
    </label>
  );
}

function Toggle({ label, checked, owned, onChange }: {
  label: string; checked: boolean; owned: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs select-none">
      <input type="checkbox" checked={checked} disabled={owned}
        onChange={(e) => onChange(e.target.checked)} />
      <span className={owned ? "text-slate-400" : "text-slate-600"}>
        {label}
      </span>
      {owned && (
        <span className="text-[9px] rounded bg-amber-50 text-amber-600
                         px-1">🔒 env</span>
      )}
    </label>
  );
}

// ---- LLM 卡 ----------------------------------------------------------------

export function LlmCard({ view, save }: {
  view: ReturnType<typeof useSettings>["view"];
  save: SaveFn;
}) {
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const s = view?.settings ?? {};
  const owned = (p: string) => isEnvOwned(view?.env_owned, p);
  const val = (p: string, fb?: any) =>
    draft[p] !== undefined ? draft[p] : getIn(s, p) ?? fb;

  function set(p: string, v: any) {
    setDraft((d) => {
      const next = { ...d };
      const segs = p.split(".");
      let node = next;
      for (const sg of segs.slice(0, -1)) {
        node[sg] = { ...(node[sg] ?? {}) };
        node = node[sg];
      }
      const last = segs[segs.length - 1]!;
      node[last] = v;
      return next;
    });
  }

  async function doSave() {
    const err = await save(draft);
    if (!err) {
      setDraft({});
      setMsg("✓ 已保存并热应用");
      setTimeout(() => setMsg(null), 2500);
    } else {
      setMsg(`✗ ${err}`);
    }
  }

  const dirty = Object.keys(draft).length > 0;

  return (
    <Card>
      <CardHeader title="AI 模型与决策"
        right={
          <>
            {msg && (
              <span className={`text-[10px] ${msg.startsWith("✓")
                ? "text-emerald-600" : "text-red-500"}`}>{msg}</span>
            )}
            <Button size="sm" variant={dirty ? "primary" : "secondary"}
              onClick={() => void doSave()}>保存</Button>
          </>
        } />
      <div className="p-3 grid grid-cols-2 gap-3 text-xs">
        <Field label="Provider" value={val("llm.provider")}
          owned={owned("llm.provider")}
          options={["deepseek", "openai_compat"]}
          onChange={(v) => set("llm.provider", v)} />
        <Field label="模型" hint="如 deepseek-chat" value={val("llm.model")}
          owned={owned("llm.model")} onChange={(v) => set("llm.model", v)} />
        <Field label="Base URL" value={val("llm.base_url")}
          owned={owned("llm.base_url")}
          onChange={(v) => set("llm.base_url", v)} />
        <Field label="Temperature" type="number"
          value={val("llm.temperature", 0)}
          owned={owned("llm.temperature")}
          onChange={(v) => set("llm.temperature", Number(v))} />

        {/* 密钥引用：只编辑规格，不碰明文 */}
        <Field label="API Key 引用类型"
          hint="机密本体放 .env 或 vault"
          value={Object.keys(getIn(s, "llm.auth_spec") ?? {})[0] ?? "env"}
          owned={owned("llm.auth_spec")}
          options={["env", "vault"]}
          onChange={(v) => set("llm.auth_spec",
            v === "env" ? { env: "DEEPSEEK_API_KEY" }
                        : { vault: "" })} />
        <Field
          label={Object.keys(getIn(s, "llm.auth_spec") ?? {})[0] === "vault"
            ? "Vault 条目名" : "环境变量名"}
          value={String(Object.values(getIn(s, "llm.auth_spec")
                        ?? {})[0] ?? "")}
          owned={owned("llm.auth_spec")}
          onChange={(v) => {
            const kind = Object.keys(getIn(s, "llm.auth_spec") ?? {})[0]
                       ?? "env";
            set("llm.auth_spec", { [kind]: v });
          }} />
      </div>
      <div className="px-3 pb-3">
        <p className="text-[10px] leading-relaxed text-slate-400">
          机密治理：此处只登记<b>引用</b>（env 变量名或 vault 条目名），
          实际密钥写在 <code className="font-mono">.env</code> 或由运维注入
          vault——配置文件与界面永不存储明文。
        </p>
      </div>
    </Card>
  );
}

// ---- 审批 + 沙箱卡 ------------------------------------------------------------

export function PolicyCards({ view, save }: {
  view: ReturnType<typeof useSettings>["view"]; save: SaveFn;
}) {
  const [approvalDraft, setApprovalDraft] =
    useState<Record<string, any>>({});
  const [sandboxDraft, setSandboxDraft] =
    useState<Record<string, any>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const s = view?.settings ?? {};
  const ownedA = (p: string) => isEnvOwned(view?.env_owned, `approval.${p}`);
  const ownedS = (p: string) => isEnvOwned(view?.env_owned, `sandbox.${p}`);

  async function saveBoth() {
    const patch: Record<string, any> = {};
    if (Object.keys(approvalDraft).length)
      patch.approval = approvalDraft;
    if (Object.keys(sandboxDraft).length)
      patch.sandbox = sandboxDraft;
    if (!Object.keys(patch).length) return;
    const err = await save(patch);
    if (!err) {
      setApprovalDraft({});
      setSandboxDraft({});
      setMsg("✓ 已保存并热应用");
      setTimeout(() => setMsg(null), 2500);
    } else {
      setMsg(`✗ ${err}`);
    }
  }

  const dirty = Object.keys(approvalDraft).length ||
                Object.keys(sandboxDraft).length;

  return (
    <Card>
      <CardHeader title="审批策略与沙箱"
        right={
          <>
            {msg && (
              <span className={`text-[10px] ${msg.startsWith("✓")
                ? "text-emerald-600" : "text-red-500"}`}>{msg}</span>
            )}
            <Button size="sm" variant={dirty ? "primary" : "secondary"}
              onClick={() => void saveBoth()} disabled={!dirty}>保存</Button>
          </>
        } />
      <div className="p-3 space-y-3 text-xs">
        <Field label="人工审批触发风险级"
          hint="达到该等级挂起等待人工确认"
          value={getIn(s, "approval.require_human_at_risk") ?? "L3"}
          owned={ownedA("require_human_at_risk")}
          options={["L0", "L1", "L2", "L3", "L4"]}
          onChange={(v) => setApprovalDraft(
            (d) => ({ ...d, require_human_at_risk: v }))} />
        <div className="flex flex-col gap-1.5 pt-1">
          <Toggle label="code.python Seatbelt 沙箱（macOS）"
            checked={Boolean(getIn(s, "sandbox.seatbelt_enabled"))}
            owned={ownedS("seatbelt_enabled")}
            onChange={(v) => setSandboxDraft(
              (d) => ({ ...d, seatbelt_enabled: v }))} />
          <Toggle label="允许 MCP 调用高风险动作（L2+）"
            checked={Boolean(getIn(s, "sandbox.mcp_allow_high_risk"))}
            owned={ownedS("mcp_allow_high_risk")}
            onChange={(v) => setSandboxDraft(
              (d) => ({ ...d, mcp_allow_high_risk: v }))} />
        </div>
      </div>
    </Card>
  );
}
