import { motion } from 'framer-motion'
import { Check, FileInput, GitBranch, Scale, ShieldCheck, X } from 'lucide-react'
import React from 'react'
import { ReviewRecord } from './api'
import { useT } from './i18n'
import { ConfBar } from './components/ui'

/** 单条记录的链路时间线：提交 → 路由 → 判定 → 网关 → 终态。
 *  running 为 true 时判定节点呼吸脉冲（模型推理中）。 */
export default function Timeline({ record, running = false }: { record: ReviewRecord; running?: boolean }) {
  const t = useT()
  const d = record.decision
  const steps: {
    icon: React.ReactNode
    title: string
    desc: string
    tone: string
    bar?: number
    pulse?: boolean
  }[] = [
    {
      icon: <FileInput size={14} />,
      title: t('tl_submit'),
      desc: `${record.item.kind} · ${record.item.id}`,
      tone: '',
    },
    {
      icon: <GitBranch size={14} />,
      title: t('tl_route'),
      desc: d.route_model
        ? `${d.route_model} · ${d.latency_ms}ms`
        : d.engine === 'heuristic'
          ? t('no_route')
          : t('route_missing'),
      tone: '',
    },
    {
      icon: <Scale size={14} />,
      title: t('tl_decide'),
      desc:
        (running ? t('running') + ' · ' : '') +
        `${d.action} · conf ${d.confidence.toFixed(2)}` +
        (d.usage && (d.usage.input_tokens || d.usage.output_tokens)
          ? ` · ${(d.usage.input_tokens ?? 0) + (d.usage.output_tokens ?? 0)} tokens`
          : ''),
      tone: d.action === 'review.reject' ? 'bad' : d.action === 'review.approve' ? 'ok' : 'warn',
      bar: d.confidence,
      pulse: running,
    },
    {
      icon: <ShieldCheck size={14} />,
      title: t('tl_gateway'),
      desc: record.via === 'auto' ? t('via_auto') : `${t('via_to_human')}（${record.via ?? 'policy'}）`,
      tone: record.via === 'auto' ? 'ok' : 'warn',
    },
    {
      icon:
        record.state === 'approved' ? (
          <Check size={14} />
        ) : record.state === 'rejected' ? (
          <X size={14} />
        ) : (
          <Check size={14} />
        ),
      title: t('tl_final'),
      desc:
        record.state === 'pending'
          ? t('waiting_human')
          : `${record.state === 'approved' ? t('done_approve') : t('done_reject')}${record.resolved_by ? ` · ${t('by')} ${record.resolved_by}` : ''}`,
      tone:
        record.state === 'approved' ? 'ok' : record.state === 'rejected' ? 'bad' : 'warn',
    },
  ]
  return (
    <ol className="timeline">
      {steps.map((s, i) => (
        <motion.li
          key={s.title}
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.06, duration: 0.25 }}
        >
          <span className={`dot ${s.tone}${s.pulse ? ' pulse' : ''}`}>{s.icon}</span>
          <div>
            <div className="t-title">{s.title}</div>
            <div className="t-desc">{s.desc}</div>
            {s.bar !== undefined && <ConfBar value={s.bar} tone={s.tone as '' | 'ok' | 'warn' | 'bad'} />}
          </div>
        </motion.li>
      ))}
    </ol>
  )
}
