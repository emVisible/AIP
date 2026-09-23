import { motion } from 'framer-motion'
import { Activity, Bot, CalendarDays, Cpu, WifiOff } from 'lucide-react'
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

function Num({ v }: { v: number }) {
  return (
    <motion.span
      key={v}
      initial={{ y: 6, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.25 }}
      style={{ display: 'inline-block', fontVariantNumeric: 'tabular-nums' }}
    >
      {v}
    </motion.span>
  )
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
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <span className={`lamp ${lamp}`}>
        {!connected ? <WifiOff size={13} /> : <Activity size={13} />}
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
      <span className="counts">
        <span className="badge warn">
          {t('c_pending')} <Num v={counts.pending} />
        </span>
        <span className="badge ok">
          {t('c_approved')} <Num v={counts.approved} />
        </span>
        <span className="badge bad">
          {t('c_rejected')} <Num v={counts.rejected} />
        </span>
        <span className="badge today">
          <CalendarDays size={11} /> {t('c_today')}{' '}
          <Num v={today.pending + today.approved + today.rejected} />
        </span>
      </span>
    </motion.div>
  )
}
