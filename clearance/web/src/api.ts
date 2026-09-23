/// <reference types="vite/client" />

export interface ReviewItem {
  id: string
  kind: string
  title: string
  body: string
  meta: Record<string, unknown>
  ts: number
}

export interface Decision {
  action: string
  confidence: number
  engine: string
  reasons: string[]
  risk: string
}

export interface ReviewRecord {
  item: ReviewItem
  decision: Decision
  state: 'pending' | 'approved' | 'rejected'
  via?: string
  resolved_by?: string
  resolved_outcome?: string
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
  health: () => req<{ ok: boolean; engine: string; version: string }>('/api/health'),
  queue: (state = '') =>
    req<{ ok: boolean; items: ReviewRecord[] }>(`/api/queue${state ? `?state=${state}` : ''}`),
  stats: () =>
    req<{ ok: boolean; counts: Record<string, number>; total: number; engine: string }>(
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
}
