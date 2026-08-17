/**
 * Per-stream sequence tracking (SPEC §5.4).
 */
import type { Message } from "./messages.js";

export type Classification = "accept" | "duplicate" | "stale" | "gap";

export class Sequencer {
  private last = new Map<string, number>();

  private key(session: string, source: string): string {
    return `${session}\u0000${source}`;
  }

  next(session: string, source: string): number {
    const k = this.key(session, source);
    const n = (this.last.get(k) ?? 0) + 1;
    this.last.set(k, n);
    return n;
  }

  lastOf(session: string, source: string): number {
    return this.last.get(this.key(session, source)) ?? 0;
  }
}

export class Receiver {
  private appliedSeq = new Map<string, number>();
  private appliedCount = new Map<string, number>();
  private ids = new Map<string, Set<string>>();
  history: Array<[string, string, number]> = [];

  private key(m: Message): string {
    return `${m.session}\u0000${m.source}`;
  }

  classify(m: Message): Classification {
    const k = this.key(m);
    const last = this.appliedSeq.get(k) ?? 0;
    if (m.seq === last + 1) return "accept";
    if (m.seq <= last) {
      return this.ids.get(k)?.has(m.id) ? "duplicate" : "stale";
    }
    return "gap";
  }

  apply(m: Message): void {
    const k = this.key(m);
    this.appliedSeq.set(k, m.seq);
    this.appliedCount.set(k, (this.appliedCount.get(k) ?? 0) + 1);
    if (!this.ids.has(k)) this.ids.set(k, new Set());
    this.ids.get(k)!.add(m.id);
    this.history.push([m.session, m.source, m.seq]);
  }

  cursor(session: string, source: string): number {
    return this.appliedSeq.get(`${session}\u0000${source}`) ?? 0;
  }

  cursors(session: string): Record<string, number> {
    const out: Record<string, number> = {};
    for (const [k, seq] of this.appliedSeq) {
      const [sess, source] = k.split("\u0000");
      if (sess === session) out[source] = seq;
    }
    return out;
  }

  appliedCountOf(session: string, source: string): number {
    return this.appliedCount.get(`${session}\u0000${source}`) ?? 0;
  }
}