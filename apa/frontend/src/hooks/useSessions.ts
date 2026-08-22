import { useQuery } from "@tanstack/react-query";

import { getAnalytics, getSessions } from "../api/endpoints/sessions";

/** 会话总览（3s 轮询兜底；SSE 到达时由 invalidate 主动刷新）*/
export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: getSessions,
    refetchInterval: 3000,
  });
}

export function useAnalytics() {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: getAnalytics,
    refetchInterval: 3000,
  });
}
