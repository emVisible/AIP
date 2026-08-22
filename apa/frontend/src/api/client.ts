/**
 * apiproxy 模式：传输无关的 wire contract 封装。
 * 所有请求经此出口；错误统一折叠为 ApiError（职责单一：调用方只处理一种异常）。
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail?: string,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  let body: unknown = {};
  try {
    body = await r.json();
  } catch {
    /* 非 JSON 响应（如 SSE 握手前的空体）*/
  }

  if (!r.ok) {
    const b = body as { error?: string; code?: string; detail?: string;
                       message?: string };
    throw new ApiError(r.status, b.error ?? b.code ?? "unknown",
                       b.detail ?? b.message);
  }
  return body as T;
}

export const post = <T>(path: string, json: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(json) });
