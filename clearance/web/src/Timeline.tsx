import { motion } from 'framer-motion'
import { Check, FileInput, GitBranch, Scale, ShieldCheck, X } from 'lucide-react'
import { ReviewRecord } from './api'
import { ConfBar } from './components/ui'

/** 单条记录的链路时间线：提交 → 路由 → 判定 → 网关 → 终态 */
export default function Timeline({ record }: { record: ReviewRecord }) {
  const d = record.decision
  const steps = [
    {
      icon: <FileInput size={14} />,
      title: '提交',
      desc: `${record.item.kind} · ${record.item.id}`,
      tone: '',
    },
    {
      icon: <GitBranch size={14} />,
      title: '路由',
      desc: d.route_model
        ? `${d.route_model} · ${d.latency_ms}ms`
        : d.engine === 'heuristic'
          ? 'heuristic（无路由）'
          : '路由信息缺失',
      tone: '',
    },
    {
      icon: <Scale size={14} />,
      title: '判定',
      desc:
        `${d.action} · conf ${d.confidence.toFixed(2)}` +
        (d.usage && (d.usage.input_tokens || d.usage.output_tokens)
          ? ` · ${(d.usage.input_tokens ?? 0) + (d.usage.output_tokens ?? 0)} tokens`
          : ''),
      tone: d.action === 'review.reject' ? 'bad' : d.action === 'review.approve' ? 'ok' : 'warn',
      bar: d.confidence,
    },
    {
      icon: <ShieldCheck size={14} />,
      title: '网关',
      desc: record.via === 'auto' ? '自动放行（置信度过线）' : `转人工（${record.via ?? 'policy'}）`,
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
      title: '终态',
      desc:
        record.state === 'pending'
          ? '等待人工'
          : `${record.state === 'approved' ? '通过' : '驳回'}${record.resolved_by ? ` · ${record.resolved_by}` : ''}`,
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
          <span className={`dot ${s.tone}`}>{s.icon}</span>
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
