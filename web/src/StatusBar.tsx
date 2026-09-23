import { motion } from 'framer-motion'
import { Bot, CalendarDays, Cpu } from 'lucide-react'
import { Counts, SidecarInfo } from './api'
import { useT } from './i18n'

interface Props {
  connected: boolean
  engine: string
  sidecar: (SidecarInfo & { ok: boolean; engine: string }) | null
  lastLatency: number | null
  counts: Counts
  today: Counts
}

export default function StatusBar({
  connected,
  engine,
  sidecar,
  lastLatency,
  counts,
  today,
}: Props) {
  const t = useT()
  const laya = engine === 'laya:sidecar' && sidecar
  const lamp = !connected ? 'off' : laya ? 'on' : 'degraded'
  const lampLabel = !connected ? t('lamp_off') : laya ? t('lamp_ok') : t('lamp_degraded')
  return (
    <motion.div
      className="statusbar"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
    >
      <span className={`lamp ${lamp}`}>
        <span className="sq" />
        {lampLabel}
      </span>
      <span className="stat">
        <Bot size={13} /> {engine}
      </span>
      {laya && sidecar && (
        <span className="stat">
          <Cpu size={13} /> {sidecar.device} · {sidecar.loaded.join('+') || '…'}
        </span>
      )}
      {lastLatency !== null && lastLatency >= 0 && (
        <span className="stat">
          {t('recent_latency')} {lastLatency}
          {t('ms')}
        </span>
      )}
      <span className="ro">
        <span className="k">{t('c_pending')}</span>
        <span className="v">
          <Num v={counts.pending} />
        </span>
      </span>
      <span className="ro">
        <span className="k">{t('c_approved')}</span>
        <span className="v">
          <Num v={counts.approved} />
        </span>
      </span>
      <span className="ro">
        <span className="k">{t('c_rejected')}</span>
        <span className="v">
          <Num v={counts.rejected} />
        </span>
      </span>
      <span className="ro">
        <span className="k">
          <CalendarDays size={11} /> {t('c_today')}
        </span>
        <span className="v">
          <Num v={today.pending + today.approved + today.rejected} />
        </span>
      </span>
    </motion.div>
  )
}

function Num({ v }: { v: number }) {
  return (
    <motion.span
      key={v}
      initial={{ y: 6, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.2 }}
      style={{ display: 'inline-block', fontVariantNumeric: 'tabular-nums' }}
    >
      {v}
    </motion.span>
  )
}
