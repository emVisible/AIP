import { motion } from 'framer-motion'
import { Check, Copy } from 'lucide-react'
import React, { useState } from 'react'

/**
 * 高频复用组件套件。溢出安全是硬契约：
 * - 所有容器默认 min-width: 0（grid/flex 子项不撑爆）
 * - 所有文本默认 overflow-wrap: anywhere（长串不断行即换）
 * - 省略只出现在有 title 兜底的单行处
 */

export type Tone = '' | 'ok' | 'warn' | 'bad'

export const KIND_ZH: Record<string, string> = {
  article: '文章',
  comment: '评论',
  product: '商品',
  ticket: '工单',
  expense: '报销',
  other: '其他',
}

export const STATE_ZH: Record<string, string> = {
  pending: '待审',
  approved: '通过',
  rejected: '驳回',
}

export function Card({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return <div className={`card ${className}`}>{children}</div>
}

export function StateTag({ state }: { state: string }) {
  const tone = state === 'approved' ? 'ok' : state === 'rejected' ? 'bad' : 'warn'
  return <span className={`tag ${tone}`}>{STATE_ZH[state] ?? state}</span>
}

export function ConfBar({ value, tone = '' }: { value: number; tone?: Tone }) {
  const pct = Math.max(0, Math.min(1, value))
  return (
    <div className="confbar">
      <motion.div
        className={`confbar-fill ${tone}`}
        initial={{ width: 0 }}
        animate={{ width: `${Math.round(pct * 100)}%` }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      />
    </div>
  )
}

export function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <p className="empty">
      {icon} {text}
    </p>
  )
}

/** 长 id/哈希：省略显示，悬停看全，点击复制 */
export function Mono({ text, className = '' }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      /* 剪贴板不可用则静默 */
    }
  }
  return (
    <span className={`mono ${className}`} title={text} onClick={copy}>
      {text}
      {copied ? <Check size={11} /> : <Copy size={11} />}
    </span>
  )
}

export function TimeText({ ts }: { ts: number }) {
  if (!ts) return <span>—</span>
  const d = new Date(ts)
  const s = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(
    d.getMinutes(),
  ).padStart(2, '0')}`
  return (
    <span className="time" title={d.toLocaleString('zh-CN')}>
      {s}
    </span>
  )
}
