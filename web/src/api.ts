/// <reference types="vite/client" />

export interface ReviewItem {
  id: string
  kind: string
  title: string
  body: string
  body_ref: string
  meta: Record<string, unknown>
  ts: number
}

export interface Decision {
  action: string
  confidence: number
  engine: string
  reasons: string[]
  latency_ms: number
  route_model: string
  usage: Record<string, number>
}

export interface ReviewRecord {
  item: ReviewItem
  decision: Decision
  state: 'pending' | 'approved' | 'rejected'
  via?: string
  resolved_by?: string
  resolved_outcome?: string
}

export interface SidecarInfo {
  device: string
  loaded: string[]
  default: string
  model_dir: string
}

export interface Health {
  ok: boolean
  engine: string
  version: string
  sidecar: (SidecarInfo & { ok: boolean; engine: string }) | null
}

export interface Counts {
  pending: number
  approved: number
  rejected: number
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  const body = await r.json()
  if (!r.ok || body.ok === false) throw new Error(body.error || `HTTP ${r.status}`)
  return body as T
}

export const api = {
  health: () => req<Health>('/api/health'),
  queue: (state = '') =>
    req<{ ok: boolean; items: ReviewRecord[] }>(`/api/queue${state ? `?state=${state}` : ''}`),
  stats: () =>
    req<{ ok: boolean; counts: Counts; total: number; engine: string; today?: Counts }>(
      '/api/stats',
    ),
  submit: (kind: string, title: string, body: string) =>
    req<ReviewRecord>('/api/review/submit', {
      method: 'POST',
      body: JSON.stringify({ kind, title, body }),
    }),
  resolve: (id: string, outcome: 'approve' | 'reject') =>
    req<ReviewRecord>(`/api/review/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ outcome, actor: 'web' }),
    }),
  contextGet: (ref: string, fields: string[] = ['body']) =>
    req<{ ok: boolean; ref: string; data: Record<string, string> }>('/api/context/get', {
      method: 'POST',
      body: JSON.stringify({ ref, fields }),
    }),
}

/** SSE 订阅：hello 快照 + submitted/resolved/stats 事件；返回取消函数。 */
export function subscribeEvents(
  onEvent: (type: string, data: Record<string, unknown>) => void,
  onError: () => void,
): () => void {
  const es = new EventSource('/api/events')
  const handler = (e: MessageEvent) => {
    try {
      onEvent((e as MessageEvent & { type: string }).type || 'message', JSON.parse(e.data))
    } catch {
      /* 忽略坏帧 */
    }
  }
  ;['hello', 'accepted', 'running', 'terminal', 'submitted', 'resolved', 'stats'].forEach((t) =>
    es.addEventListener(t, handler as EventListener),
  )
  es.onerror = () => onError()
  return () => es.close()
}
