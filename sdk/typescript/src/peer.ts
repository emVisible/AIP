/**
 * AIP peer: send helpers with automatic per-stream sequence assignment.
 */
import {
  ErrorCode,
  Message,
  MessageOptions,
  ResultStatus,
  makeAction,
  makeError,
  makeEvent,
  makeResult,
  messageFromDict,
} from "./messages.js";
import { Receiver, Sequencer } from "./sequence.js";
import { Session } from "./session.js";
import { Transport } from "./transport.js";

export class AIPPeer {
  readonly source: string;
  readonly sessionId: string;
  readonly identity: string;
  transport?: Transport;
  seq = new Sequencer();
  receiver = new Receiver();
  session: Session;

  constructor(
    source: string,
    sessionId: string,
    options: { transport?: Transport; identity?: string } = {},
  ) {
    this.source = source;
    this.sessionId = sessionId;
    this.identity = options.identity ?? source;
    this.transport = options.transport;
    this.session = new Session(sessionId);
    this.session.receiver = this.receiver;
  }

  send(m: Message): Message {
    if (!m.seq) m.seq = this.seq.next(this.sessionId, this.source);
    this.transport?.send(m);
    return m;
  }

  sendEvent(name: string, data?: Record<string, unknown>, opts: MessageOptions = {}): Message {
    return this.send(makeEvent(this.sessionId, this.source, name, data, opts));
  }

  sendAction(
    name: string,
    options: {
      target?: string;
      params?: Record<string, unknown>;
      expect?: { event: string };
    } = {},
    opts: MessageOptions = {},
  ): Message {
    return this.send(makeAction(this.sessionId, this.source, name, options, opts));
  }

  sendResult(
    status: ResultStatus,
    inReplyTo: string,
    options: {
      data?: Record<string, unknown>;
      code?: string;
      message?: string;
      duplicate?: boolean;
      originalResultId?: string;
      retry?: { allowed: boolean; after_ms?: number };
    } = {},
    opts: MessageOptions = {},
  ): Message {
    return this.send(makeResult(this.sessionId, this.source, status, inReplyTo, options, opts));
  }

  sendError(
    code: ErrorCode,
    options: { message?: string; retry?: { allowed: boolean; after_ms?: number } } = {},
    opts: MessageOptions = {},
  ): Message {
    return this.send(makeError(this.sessionId, this.source, code, options, opts));
  }

  handle(raw: unknown): { kind: "accept" | "duplicate" | "stale" | "gap"; message: Message } {
    const msg = messageFromDict(raw as Record<string, unknown>);
    const kind = this.receiver.classify(msg);
    if (kind === "accept") this.receiver.apply(msg);
    return { kind, message: msg };
  }
}