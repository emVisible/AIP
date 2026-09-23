import React, { useCallback, useEffect, useState } from 'react'
import { api, ReviewRecord } from './api'
import './styles.css'

type Filter = '' | 'pending' | 'approved' | 'rejected'
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'pending', label: '待审' },
  { key: 'approved', label: '已通过' },
  { key: 'rejected', label: '已驳回' },
  { key: '', label: '全部' },
]
const KINDS = ['article', 'comment', 'product', 'ticket', 'expense', 'other']

export default function App() {
  const [filter, setFilter] = useState<Filter>('pending')
  const [items, setItems] = useState<ReviewRecord[]>([])
  const [selected, setSelected] = useState<ReviewRecord | null>(null)
  const [stats, setStats] = useState<{ counts: Record<string, number>; engine: string } | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ kind: 'article', title: '', body: '' })

  const refresh = useCallback(async () => {
    try {
      const [q, s] = await Promise.all([api.queue(filter), api.stats()])
      setItems(q.items)
      setStats({ counts: s.counts, engine: s.engine })
      setError('')
      if (selected) {
        const still = q.items.find((i) => i.item.id === selected.item.id) ?? null
        setSelected(still)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [filter, selected?.item.id])

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const resolve = async (outcome: 'approve' | 'reject') => {
    if (!selected) return
    await api.resolve(selected.item.id, outcome)
    setSelected(null)
    refresh()
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim() && !form.body.trim()) return
    await api.submit(form.kind, form.title, form.body)
    setForm({ kind: 'article', title: '', body: '' })
    refresh()
  }

  return (
    <div className="layout">
      <header>
        <h1>Clearance 放行</h1>
        <span className="sub">AIP 的产品实现 · 通用后台审核</span>
        {stats && (
          <span className="badges">
            <span className="badge">engine: {stats.engine}</span>
            <span className="badge warn">待审 {stats.counts.pending ?? 0}</span>
            <span className="badge ok">通过 {stats.counts.approved ?? 0}</span>
            <span className="badge bad">驳回 {stats.counts.rejected ?? 0}</span>
          </span>
        )}
      </header>
      {error && <div className="error">后端未连接（先跑 start.sh）：{error}</div>}
      <div className="main">
        <section className="queue">
          <nav>
            {FILTERS.map((f) => (
              <button
                key={f.key || 'all'}
                className={filter === f.key ? 'active' : ''}
                onClick={() => {
                  setFilter(f.key)
                  setSelected(null)
                }}
              >
                {f.label}
              </button>
            ))}
          </nav>
          <ul>
            {items.map((r) => (
              <li
                key={r.item.id}
                className={selected?.item.id === r.item.id ? 'sel' : ''}
                onClick={() => setSelected(r)}
              >
                <span className={`state ${r.state}`}>{r.state}</span>
                <span className="kind">{r.item.kind}</span>
                <span className="title">{r.item.title || '(无标题)'}</span>
                <span className="conf">{r.decision.confidence.toFixed(2)}</span>
              </li>
            ))}
          </ul>
          {items.length === 0 && <p className="empty">空队列——从右边提交第一条吧。</p>}
        </section>
        <section className="detail">
          {selected ? (
            <>
              <h2>{selected.item.title || '(无标题)'}</h2>
              <p className="meta">
                {selected.item.kind} · {selected.item.id} · conf{' '}
                {selected.decision.confidence.toFixed(2)} · {selected.decision.engine} ·{' '}
                {selected.decision.action}
              </p>
              <pre>{selected.item.body}</pre>
              <ul className="reasons">
                {selected.decision.reasons.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
              {selected.state === 'pending' ? (
                <div className="actions">
                  <button className="ok" onClick={() => resolve('approve')}>
                    通过
                  </button>
                  <button className="bad" onClick={() => resolve('reject')}>
                    驳回
                  </button>
                </div>
              ) : (
                <p className="meta">
                  已{selected.state === 'approved' ? '通过' : '驳回'}
                  {selected.resolved_by ? ` · by ${selected.resolved_by}` : ''}
                </p>
              )}
            </>
          ) : (
            <p className="empty">左侧选一条查看详情 / 人审。</p>
          )}
          <hr />
          <h3>提交审核</h3>
          <form onSubmit={submit}>
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <input
              placeholder="标题"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
            <textarea
              placeholder="正文"
              rows={4}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
            />
            <button type="submit">提交</button>
          </form>
        </section>
      </div>
    </div>
  )
}
