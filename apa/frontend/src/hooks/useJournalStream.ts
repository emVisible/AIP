import { useEffect, useRef } from "react";
import type { JournalRecord } from "../api/types";

/**
 * 订阅 journal 实时流（SSE）。
 * 单一职责：只负责连接生命周期与帧解析，数据处理交给调用方回调。
 *
 * 后端：GET /api/journal/stream（text/event-stream）
 */
export function useJournalStream(
  onRecord: (record: JournalRecord) => void,
  enabled = true,
) {
  const cbRef = useRef(onRecord);
  cbRef.current = onRecord; // 避免闭包过期（best practice）

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource("/api/journal/stream");
    es.onmessage = (ev) => {
      try {
        cbRef.current(JSON.parse(ev.data));
      } catch {
        /* 心跳注释帧等非 JSON 忽略 */
      }
    };
    es.onerror = () => es.close(); // 断线由 Query 轮询兜底
    return () => es.close();
  }, [enabled]);
}
