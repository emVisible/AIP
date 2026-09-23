import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, Inbox, Send } from 'lucide-react'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Counts, ReviewRecord, SidecarInfo, api, subscribeEvents } from './api'
import StatusBar from './StatusBar'
import Timeline from './Timeline'
import { Card, EmptyState, KIND_ZH, Mono, StateTag, TimeText } from './components/ui'
import './styles.css'

type Filter = '' | 'pending' | 'approved' | 'rejected'
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'pending', label: '待审' },
  { key: 'approved', label: '已通过' },
  { key: 'rejected', label: '已驳回' },
  { key: '', label: '全部' },
]
const KINDS = ['article', 'comment', 'product', 'ticket', 'expense', 'other']
type Sidecar = (SidecarInfo & { ok: boolean; engine: string }) | null

export default function App() {
  const [filter, setFilter] = useState<Filter>('pending')
  const [items, setItems] = useState<ReviewRecord[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [counts, setCounts] = useState<Counts>({ pending: 0, approved: 0, rejected: 0 })
  const [engine, setEngine] = useState('…')
  const [sidecar, setSidecar] = useState<Sidecar>(null)
  const [lastLatency, setLastLatency] = useState<number | null>(null)
  const [connected, setConnected] = useState(false)
  const [toast, setToast] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [progress, setProgress] = useState<Record<string, string>>({})
  const [form, setForm] = useState({ kind: 'article', title: '', body: '' })
  const filterRef = useRef(filter)
  filterRef.current = filter

  const loadQueue = useCallback(async (f: Filter) => {
    const q = await api.queue(f)
    setItems(q.items)
  }, [])

  const loadMeta = useCallback(async () => {
    const [h, s] = await Promise.all([api.health(), api.stats()])
    setEngine(h.engine)
    setSidecar(h.sidecar)
    setCounts(s.counts)
    setConnected(true)
  }, [])

  // 首屏 + SSE 实时流（断线回落 5s 轮询）
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null
    loadQueue(filterRef.current).catch(() => setConnected(false))
    loadMeta().catch(() => setConnected(false))
    const off = subscribeEvents(
      (type, data) => {
        if (type === 'hello') {
          const c = data.counts as Counts | undefined
          if (c) setCounts(c)
          setConnected(true)
          return
        }
        if (type === 'stats') {
          const c = data as unknown as { counts: Counts }
          if (c.counts) setCounts(c.counts)
          return
        }
        if (type === 'accepted' || type === 'running') {
          const id = (data as { id?: string }).id
          if (id) setProgress((p) => ({ ...p, [id]: type }))
          return
        }
        if (type === 'terminal') {
          const id = (data as { id?: string }).id
          if (id)
            setProgress((p) => {
              const n = { ...p }
              delete n[id]
              return n
            })
        }
        loadQueue(filterRef.current).catch(() => setConnected(false))
        loadMeta().catch(() => setConnected(false))
      },
      () => {
        setConnected(false)
        if (!timer) {
          timer = setInterval(() => {
            loadQueue(filterRef.current)
              .then(loadMeta)
              .catch(() => setConnected(false))
          }, 5000)
        }
      },
    )
    return () => {
      off()
      if (timer) clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadQueue(filter).catch(() => setConnected(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const selected = items.find((i) => i.item.id === selectedId) ?? null
  const [fullBody, setFullBody] = useState<string | null>(null)
  const [bodyLoading, setBodyLoading] = useState(false)

  // CoD：正文引用化时按需拉全文，首屏只摘要
  useEffect(() => {
    setFullBody(null)
    if (!selected) return
    if (selected.item.body) {
      setFullBody(selected.item.body)
      return
    }
    if (!selected.item.body_ref) return
    setBodyLoading(true)
    api
      .contextGet(selected.item.body_ref, ['body'])
      .then((r) => setFullBody(r.data.body ?? ''))
      .catch(() => setFullBody('（全文加载失败）'))
      .finally(() => setBodyLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  const flash = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 2200)
  }

  const resolve = async (outcome: 'approve' | 'reject') => {
    if (!selected) return
    await api.resolve(selected.item.id, outcome)
    flash(outcome === 'approve' ? '已通过' : '已驳回')
    setSelectedId(null)
    loadQueue(filterRef.current).catch(() => {})
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if ((!form.title.trim() && !form.body.trim()) || submitting) return
    setSubmitting(true)
    try {
      const rec = await api.submit(form.kind, form.title, form.body)
      if (rec.decision.latency_ms >= 0) setLastLatency(rec.decision.latency_ms)
      setForm({ kind: 'article', title: '', body: '' })
      flash(rec.state === 'pending' ? '已提交，转人工' : rec.state === 'approved' ? '已提交，自动通过' : '已提交，自动驳回')
      setSelectedId(rec.item.id)
      loadQueue(filterRef.current).catch(() => {})
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="layout">
      <header>
        <div>
          <h1>Clearance 放行</h1>
          <span className="sub">AIP 的产品实现 · 通用后台审核</span>
        </div>
      </header>

      <StatusBar
        connected={connected}
        engine={engine}
        sidecar={sidecar}
        lastLatency={lastLatency}
        counts={counts}
      />
      {!connected && <div className="error">后端未连接（先跑 ./start.sh），5 秒后重试。</div>}

      <div className="main">
        <Card className="queue">
          <nav>
            {FILTERS.map((f) => (
              <button
                key={f.key || 'all'}
                className={filter === f.key ? 'active' : ''}
                onClick={() => {
                  setFilter(f.key)
                  setSelectedId(null)
                }}
              >
                {f.label}
              </button>
            ))}
          </nav>
          <ul>
            <AnimatePresence initial={false}>
              {items.map((r) => (
                <motion.li
                  key={r.item.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  transition={{ duration: 0.22 }}
                  className={selectedId === r.item.id ? 'sel' : ''}
                  onClick={() => setSelectedId(r.item.id)}
                >
                  <StateTag state={r.state} />
                  <span className="kind">{KIND_ZH[r.item.kind] ?? r.item.kind}</span>
                  <span className="title" title={r.item.title}>
                    {r.item.title || '(无标题)'}
                  </span>
                  <TimeText ts={r.item.ts} />
                  <span className="conf">{r.decision.confidence.toFixed(2)}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
          {items.length === 0 && <EmptyState icon={<Inbox size={16} />} text="空队列——从右边提交第一条吧。" />}
        </Card>

        <Card className="detail">
          <AnimatePresence mode="wait">
            {selected ? (
              <motion.div
                key={selected.item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
              >
                <h2>{selected.item.title || '(无标题)'}</h2>
                <p className="meta">
                  {KIND_ZH[selected.item.kind] ?? selected.item.kind} ·{' '}
                  <Mono text={selected.item.id} /> · <TimeText ts={selected.item.ts} />
                </p>
                <pre>{bodyLoading ? '全文加载中…' : (fullBody ?? '')}</pre>
                <Timeline record={selected} running={progress[selected.item.id] === 'running'} />
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
              </motion.div>
            ) : (
              <motion.p
                key="empty"
                className="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                左侧选一条查看链路 / 人审。
              </motion.p>
            )}
          </AnimatePresence>
          <hr />
          <h3>
            <Send size={14} /> 提交审核
          </h3>
          <form onSubmit={submit}>
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_ZH[k]}（{k}）
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
            <button type="submit" disabled={submitting}>
              {submitting ? '判定中…' : '提交'}
            </button>
          </form>
        </Card>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            className="toast"
            initial={{ opacity: 0, y: 16, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: 8, x: '-50%' }}
          >
            <CheckCircle2 size={15} /> {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
