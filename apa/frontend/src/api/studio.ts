/**
 * APA Studio Protocol v1 —— 类型化 RPC 客户端（H3）。
 *
 * 类型来自单源生成的 shared/studioProtocol.ts；
 * 旧 REST 端点经此通道逐步过渡（fusion 文档 §5 H3 验收）。
 */
import type { RpcRequest, RpcResponse } from "../shared/studioProtocol";

export class StudioRpcError extends Error {
  constructor(public code: string,
              message: string,
              public data: Record<string, unknown> = {}) {
    super(`[${code}] ${message}`);
    this.name = "StudioRpcError";
  }
}

function rpcId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 统一调用入口：studioRpc<T>("session.append", {...}) */
export async function studioRpc<T = unknown>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  const body: RpcRequest = { id: rpcId(), method, params };
  const r = await fetch("/api/studio/rpc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = (await r.json()) as RpcResponse;
  if (!d.ok) {
    throw new StudioRpcError(d.error?.code ?? "internal_error",
                             d.error?.message ?? "rpc failed",
                             d.error?.data);
  }
  return d.result as T;
}
