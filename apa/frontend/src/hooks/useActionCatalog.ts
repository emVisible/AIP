/**
 * 动作目录共享数据源 —— 设计器内唯一拉取点。
 *
 * 背景：此前 DesignerPage（无重试）与 CatalogPanel（react-query retry）
 * 各自拉取 /api/registry/actions，启动竞态下页面级 catalog 永久为空，
 * 拖入步骤只能显示英文动作名。本 hook 以相同 queryKey 去重合并，
 * 两个消费方共享同一缓存与重试策略。
 */
import { useQuery } from "@tanstack/react-query";

import type { ActionMeta } from "../api/types";

export function useActionCatalog(): {
  catalog: Record<string, ActionMeta>;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const query = useQuery({
    queryKey: ["registry", "actions"],
    queryFn: () =>
      fetch("/api/registry/actions").then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Record<string, ActionMeta>>;
      }),
    retry: 2,
    staleTime: 60_000,
  });
  return {
    catalog: query.data ?? {},
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: () => void query.refetch(),
  };
}
