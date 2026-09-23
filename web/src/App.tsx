import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, Inbox, Send } from 'lucide-react'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Counts, ReviewRecord, SidecarInfo, api, subscribeEvents } from './api'
import StatusBar from './StatusBar'
import Timeline from './Timeline'
import { Card, EmptyState, Mono, StateTag, TimeText, kindName } from './components/ui'
import { LangCtx, StrKey, useLang, useT } from './i18n'
import { SAMPLES } from './samples'
import './styles.css'

type Filter = '' | 'pending' | 'approved' | 'rejected'
const FILTER_KEYS: { key: Filter; label: StrKey }[] = [
  { key: 'pending', label: 'f_pending' },
  { key: 'approved', label: 'f_approved' },
  { key: 'rejected', label: 'f_rejected' },
  { key: '', label: 'f_all' },
]
const KINDS = ['article', 'comment', 'product', 'ticket', 'expense', 'other']
type Sidecar = (SidecarInfo & { ok: boolean; engine: string }) | null

function Shell() {
  const [lang, setLang] = useLang()
  const t = useT()
  const [filter, setFilter] = useState<Filter>('pending')
  const [items, setItems] = useState<ReviewRecord[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [counts, setCounts] = useState<Counts>({ pending: 0, approved: 0, rejected: 0 })
  const [today, setToday] = useState<Counts>({ pending: 0, approved: 0, rejected: 0 })
  const [engine, setEngine] = useState('…')
  const [sidecar, setSidecar] = useState<Sidecar>(null)
  const [lastLatency, setLastLatency] = useState<number | null>(null)
  const [connected, setConnected] = useState(false)
  const [toast, setToast] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [batching, setBatching] = useState(false)
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
    if (s.today) setToday(s.today)
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
          const todayCounts = (data as { today?: Counts }).today
          if (todayCounts) setToday(todayCounts)
          setConnected(true)
          return
        }
        if (type === 'stats') {
          const c = data as unknown as { counts: Counts; today?: Counts }
          if (c.counts) setCounts(c.counts)
          if (c.today) setToday(c.today)
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
    setChecked(new Set())
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
      .catch(() => setFullBody(t('body_failed')))
      .finally(() => setBodyLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  const flash = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 2200)
  }

  const doResolve = async (id: string, outcome: 'approve' | 'reject') => {
    await api.resolve(id, outcome)
  }

  const resolve = async (outcome: 'approve' | 'reject') => {
    if (!selected) return
    await doResolve(selected.item.id, outcome)
    flash(outcome === 'approve' ? t('toast_done_approve') : t('toast_done_reject'))
    setSelectedId(null)
    loadQueue(filterRef.current).catch(() => {})
  }

  const batchResolve = async (outcome: 'approve' | 'reject') => {
    if (checked.size === 0 || batching) return
    setBatching(true)
    try {
      await Promise.all([...checked].map((id) => doResolve(id, outcome)))
      flash(t('batch_done'))
      setChecked(new Set())
      setSelectedId(null)
      loadQueue(filterRef.current).catch(() => {})
    } finally {
      setBatching(false)
    }
  }

  const toggleCheck = (id: string) => {
    setChecked((prev) => {
      const n = new Set(prev)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if ((!form.title.trim() && !form.body.trim()) || submitting) return
    setSubmitting(true)
    try {
      const rec = await api.submit(form.kind, form.title, form.body)
      if (rec.decision.latency_ms >= 0) setLastLatency(rec.decision.latency_ms)
      setForm({ kind: 'article', title: '', body: '' })
      flash(
        rec.state === 'pending'
          ? t('toast_pending')
          : rec.state === 'approved'
            ? t('toast_approved')
            : t('toast_rejected'),
      )
      setSelectedId(rec.item.id)
      loadQueue(filterRef.current).catch(() => {})
    } finally {
      setSubmitting(false)
    }
  }

  const fillSample = (id: string) => {
    const s = SAMPLES.find((x) => x.id === id)
    if (!s) return
    setForm({ kind: s.kind, title: s.title[lang], body: s.body[lang] })
  }

  // 快捷键：j/k 移动，a 通过，r 驳回（输入框内不触发）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) return
      if (e.key === 'j' || e.key === 'k') {
        if (items.length === 0) return
        const idx = items.findIndex((i) => i.item.id === selectedId)
        const next =
          e.key === 'j'
            ? items[Math.min(items.length - 1, idx + 1)]
            : items[Math.max(0, idx - 1 < 0 ? 0 : idx - 1)]
        if (next) setSelectedId(next.item.id)
      } else if ((e.key === 'a' || e.key === 'r') && selected && selected.state === 'pending') {
        resolve(e.key === 'a' ? 'approve' : 'reject').catch(() => {})
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, selectedId, selected?.state])
  return (
    <div className="layout">
      <header className="brand">
        <img src="/logo.svg" alt="Clearance" className="mark" />
        <div>
          <h1>
            {t('title')} <span className="wordmark">{t('titleEn')}</span>
          </h1>
          <span className="sub">{t('sub')}</span>
        </div>
        <button className="lang-toggle" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}>
          {t('toggle_lang')}
        </button>
      </header>

      <StatusBar
        connected={connected}
        engine={engine}
        sidecar={sidecar}
        lastLatency={lastLatency}
        counts={counts}
        today={today}
      />
      {!connected && <div className="error">{t('err_backend')}</div>}

      <div className="main">
        <Card className="queue">
          <nav>
            {FILTER_KEYS.map((f) => (
              <button
                key={f.key || 'all'}
                className={filter === f.key ? 'active' : ''}
                onClick={() => {
                  setFilter(f.key)
                  setSelectedId(null)
                }}
              >
                {t(f.label)}
              </button>
            ))}
          </nav>
          {filter === 'pending' && checked.size > 0 && (
            <div className="batchbar">
              <span>
                {t('batch_bar')} {checked.size}
              </span>
              <button disabled={batching} onClick={() => batchResolve('approve')}>
                {t('batch_approve')}
              </button>
              <button disabled={batching} onClick={() => batchResolve('reject')}>
                {t('batch_reject')}
              </button>
            </div>
          )}
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
                  {filter === 'pending' && r.state === 'pending' && (
                    <input
                      type="checkbox"
                      checked={checked.has(r.item.id)}
                      onChange={() => toggleCheck(r.item.id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                  <StateTag state={r.state} lang={lang} />
                  <span className="kind">{kindName(lang, r.item.kind)}</span>
                  <span className="title" title={r.item.title}>
                    {r.item.title || t('no_title')}
                  </span>
                  <TimeText ts={r.item.ts} />
                  <span className="conf">{r.decision.confidence.toFixed(2)}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
          {items.length === 0 && <EmptyState icon={<Inbox size={16} />} text={t('empty_queue')} />}
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
                <h2>{selected.item.title || t('no_title')}</h2>
                <p className="meta">
                  {kindName(lang, selected.item.kind)} · <Mono text={selected.item.id} /> ·{' '}
                  <TimeText ts={selected.item.ts} />
                </p>
                <pre>{bodyLoading ? t('loading_body') : (fullBody ?? '')}</pre>
                <Timeline record={selected} running={progress[selected.item.id] === 'running'} />
                <p className="meta">{t('reasons_note')}</p>
                <ul className="reasons">
                  {selected.decision.reasons.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
                {selected.state === 'pending' ? (
                  <div className="actions">
                    <button className="ok" onClick={() => resolve('approve')}>
                      {t('btn_approve')}
                    </button>
                    <button className="bad" onClick={() => resolve('reject')}>
                      {t('btn_reject')}
                    </button>
                  </div>
                ) : (
                  <p className="meta">
                    {selected.state === 'approved' ? t('done_approve') : t('done_reject')}
                    {selected.resolved_by ? ` · ${t('by')} ${selected.resolved_by}` : ''}
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
                {t('empty_detail')}
              </motion.p>
            )}
          </AnimatePresence>
          <hr />
          <h3>
            <Send size={14} /> {t('form_title')}
          </h3>
          <div className="samples">
            <span className="samples-label">{t('samples_title')}</span>
            <div className="chips">
              {SAMPLES.map((s) => (
                <button key={s.id} className="chip" onClick={() => fillSample(s.id)}>
                  {s.title[lang]}
                </button>
              ))}
              <button
                className="chip ghost"
                onClick={() => setForm({ kind: 'article', title: '', body: '' })}
              >
                {t('btn_clear')}
              </button>
            </div>
          </div>
          <form onSubmit={submit}>
            <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {kindName(lang, k)}（{k}）
                </option>
              ))}
            </select>
            <input
              placeholder={t('form_title_ph')}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
            <textarea
              placeholder={t('form_body_ph')}
              rows={4}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
            />
            <button type="submit" disabled={submitting}>
              {submitting ? t('btn_submitting') : t('btn_submit')}
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

export default function App() {
  const [lang, setLang] = useLang()
  return (
    <LangCtx.Provider value={{ lang, setLang }}>
      <Shell />
    </LangCtx.Provider>
  )
}
