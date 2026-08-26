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
  // 路径归一化：调用方可能传入已带 /api 的路径（历史书写不一），
  // 统一剥离后重拼，杜绝 /api/api/* 双前缀 404（桌面拾取/试运行/保存等曾全部中招）
  const p = path.startsWith("/api/") ? path.slice(4) : path;
  const r = await fetch(`/api${p}`, {
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
