/**
 * Studio notification 下行订阅（H3 二期）。
 * SSE /api/studio/events → onEvent(method, payload)；
 * sid 过滤可选；回调经 ref 避免重连。
 */
import { useEffect, useRef } from "react";

export function useStudioEvents(
  onEvent: (method: string, payload: Record<string, unknown>) => void,
  sid?: string,
) {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const url = new URL("/api/studio/events", window.location.origin);
    if (sid) url.searchParams.set("sid", sid);
    const es = new EventSource(url.toString());
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d?.method) {
          cbRef.current(d.method as string,
                        (d.payload ?? {}) as Record<string, unknown>);
        }
      } catch { /* 坏帧忽略 */ }
    };
    return () => es.close();
  }, [sid]);
}
