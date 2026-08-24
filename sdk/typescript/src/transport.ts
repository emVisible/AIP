/**
 * Transport abstraction (SPEC §7). In-memory endpoint + WebSocket binding.
 * `parseFrame` implements the E5 framing rule: one JSON document per frame.
 */
import type { Message } from "./messages.js";
import { messageToDict } from "./messages.js";
import { WebSocket, WebSocketServer } from "ws";

export interface Transport {
  send(message: Message): void;
  close?(): void | Promise<void>;
}

export interface TransportHandlers {
  onMessage?: (m: Message) => void;
  onError?: (e: Error) => void;
}

export class InMemoryEndpoint implements Transport {
  inbox: Message[] = [];
  private out?: (m: Message) => void;

  attach(fn: (m: Message) => void): void {
    this.out = fn;
  }

  send(m: Message): void {
    this.inbox.push(m);
    this.out?.(m);
  }
}

export function connectEndpoints(a: InMemoryEndpoint, b: InMemoryEndpoint): void {
  a.attach((m) => b.send(m));
  b.attach((m) => a.send(m));
}

/** E5: a text frame carries exactly one JSON document (SPEC §10 E5). */
export function parseFrame(text: string): { message?: Message; error?: string } {
  const trimmed = text.trim();
  if (!trimmed) return { error: "empty frame" };
  try {
    // JSON.parse rejects trailing content, so a frame with two objects fails here.
    const value: unknown = JSON.parse(trimmed);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { error: "frame is not a single JSON object" };
    }
    return { message: value as Message };
  } catch {
    return { error: "invalid JSON frame" };
  }
}

/** WebSocket server-side transport. Emits a parsed Message or an error. */
export class WsServerTransport implements Transport {
  readonly server: WebSocketServer;
  private socket?: WebSocket;
  onMessage?: (m: Message) => void;
  onError?: (e: Error) => void;

  constructor(options: { port?: number } & TransportHandlers = {}) {
    this.onMessage = options.onMessage;
    this.onError = options.onError;
    this.server = new WebSocketServer({ port: options.port ?? 0 });
    this.server.on("connection", (socket) => {
      this.socket = socket;
      socket.on("message", (data) => this.receive(data.toString()));
    });
  }

  private receive(text: string): void {
    const r = parseFrame(text);
    if (r.error) {
      this.onError?.(new Error(r.error));
      return;
    }
    this.onMessage?.(r.message!);
  }

  port(): number {
    const addr = this.server.address();
    return typeof addr === "object" && addr !== null ? addr.port : 0;
  }

  send(m: Message): void {
    this.socket?.send(JSON.stringify(messageToDict(m)));
  }

  close(): Promise<void> {
    return new Promise((resolve) => this.server.close(() => resolve()));
  }
}

/** WebSocket client-side transport. */
export class WsClientTransport implements Transport {
  private ws: WebSocket;
  private _isOpen = false;
  private _onOpenCb?: () => void;
  onMessage?: (m: Message) => void;
  onError?: (e: Error) => void;

  /**
   * Binding-level open callback.
   * 竞态防护：回环连接可能在调用方赋值 onOpen 前已 OPEN——
   * setter 语义保证「赋值即补触发」（恰好一次）。
   */
  set onOpen(cb: (() => void) | undefined) {
    this._onOpenCb = cb;
    if (cb && this._isOpen) queueMicrotask(cb);
  }

  constructor(url: string, options: TransportHandlers = {}) {
    this.onMessage = options.onMessage;
    this.onError = options.onError;
    this.ws = new WebSocket(url);
    this.ws.on("open", () => {
      this._isOpen = true;
      this._onOpenCb?.();
    });
    this.ws.on("message", (data) => this.receive(data.toString()));
    this.ws.on("error", (e) => this.onError?.(e));
  }

  private receive(text: string): void {
    const r = parseFrame(text);
    if (r.error) {
      this.onError?.(new Error(r.error));
      return;
    }
    this.onMessage?.(r.message!);
  }

  send(m: Message): void {
    this.ws.send(JSON.stringify(messageToDict(m)));
  }

  /**
   * Send a raw text frame (E5: exactly one JSON object).
   * For binding-level control frames (hello/ping) that never consume
   * per-stream seq (SPEC D4) — not for application messages.
   */
  sendRaw(text: string): void {
    this.ws.send(text);
  }

  close(): void {
    this.ws.close();
  }
}