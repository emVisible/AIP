/**
 * apiproxy 模式：传输无关的 wire contract 封装。
 * 所有请求经此出口；错误统一折叠为 ApiError（职责单一：调用方只处理一种异常）。
 */
export class ApiError extends Error {
    status;
    code;
    detail;
    constructor(status, code, detail) {
        super(code);
        this.status = status;
        this.code = code;
        this.detail = detail;
        this.name = "ApiError";
    }
}
export async function api(path, init) {
    const r = await fetch(`/api${path}`, {
        headers: { "Content-Type": "application/json", ...init?.headers },
        ...init,
    });
    let body = {};
    try {
        body = await r.json();
    }
    catch {
        /* 非 JSON 响应（如 SSE 握手前的空体）*/
    }
    if (!r.ok) {
        const b = body;
        throw new ApiError(r.status, b.error ?? b.code ?? "unknown", b.detail ?? b.message);
    }
    return body;
}
export const post = (path, json) => api(path, { method: "POST", body: JSON.stringify(json) });
