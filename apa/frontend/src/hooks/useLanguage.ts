/**
 * 语言偏好 hook —— localStorage 持久化。
 * 默认 "zh"（中文优先）；Settings 切换后全 app 响应。
 */
import { useCallback, useState } from "react";

type Lang = "zh" | "en";
const KEY = "apa_language";

export function useLanguage(): [Lang, (l: Lang) => void] {
  const [lang, setLangState] = useState<Lang>(() => {
    try { return (localStorage.getItem(KEY) as Lang) || "zh"; }
    catch { return "zh"; }
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(KEY, l); } catch { /* private mode */ }
  }, []);

  return [lang, setLang];
}

/** 快速读取（非 hook 场景）。 */
export function getLanguage(): Lang {
  try { return (localStorage.getItem(KEY) as Lang) || "zh"; }
  catch { return "zh"; }
}
