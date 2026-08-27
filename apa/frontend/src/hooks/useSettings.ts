/**
 * 设置子系统前端状态（H7b）—— settings.get/update 的类型化封装。
 *
 * env-owned 叶子在后端被包装为 {"value":x,"_source":"env:path"}，
 * 本模块提供解包与只读判定，供设置卡渲染。
 */
import { useCallback, useEffect, useState } from "react";

import { studioRpc } from "../api/studio";

export interface SettingsView {
  version: number;
  settings: Record<string, any>;
  env_owned: string[];
}

export function useSettings() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(() => {
    studioRpc<SettingsView>("settings.get")
      .then(setView)
      .catch((e) => setError(e?.message ?? String(e)));
  }, []);

  useEffect(refresh, [refresh]);

  /** 应用 patch；成功后重拉 redacted 视图。返回错误消息或 null。 */
  const save = useCallback(async (patch: Record<string, any>) => {
    setSaving(true);
    try {
      await studioRpc("settings.update", { patch, write_back: true });
      const fresh = await studioRpc<SettingsView>("settings.get");
      setView(fresh);
      setError("");
      return null;
    } catch (e: any) {
      const msg = e?.message ?? String(e);
      setError(msg);
      return msg;
    } finally {
      setSaving(false);
    }
  }, []);

  return { view, error, saving, save, refresh };
}

/** 读取嵌套路径值；env-owned 包装自动解包。 */
export function getIn(obj: any, dotted: string): any {
  let node = obj;
  for (const seg of dotted.split(".")) {
    if (node == null || typeof node !== "object") return undefined;
    node = node[seg];
  }
  if (node && typeof node === "object" && "_source" in node) {
    return (node as any).value;
  }
  return node;
}

/** 该路径是否被环境变量接管（只读）。 */
export function isEnvOwned(envOwned: string[] | undefined,
                          dotted: string): boolean {
  return (envOwned ?? []).includes(dotted);
}
