import { motion } from 'framer-motion'
import { Activity, Bot, Cpu, WifiOff } from 'lucide-react'
import { Counts, SidecarInfo } from './api'

interface Props {
  connected: boolean
  engine: string
  sidecar: (SidecarInfo & { ok: boolean; engine: string }) | null
  lastLatency: number | null
  counts: Counts
}

export default function StatusBar({ connected, engine, sidecar, lastLatency, counts }: Props) {
  const laya = engine === 'laya:sidecar' && sidecar
  const lamp = !connected ? 'off' : laya ? 'on' : 'degraded'
  const lampLabel = !connected ? '后端失联' : laya ? 'Laya 在线' : 'heuristic 兜底'
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
          <Cpu size={13} /> {sidecar.device} · {sidecar.loaded.join('+') || '预热中'}
        </span>
      )}
      {lastLatency !== null && lastLatency >= 0 && (
        <span className="stat">最近判定 {lastLatency}ms</span>
      )}
      <span className="counts">
        <span className="badge warn">待审 {counts.pending}</span>
        <span className="badge ok">通过 {counts.approved}</span>
        <span className="badge bad">驳回 {counts.rejected}</span>
      </span>
    </motion.div>
  )
}
