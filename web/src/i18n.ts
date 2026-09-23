import React from 'react'

export type Lang = 'zh' | 'en'

const DICT = {
  zh: {
    title: '清放行',
    titleEn: 'Clearance',
    sub: '中文后台审核网关 · 置信门控 + 全审计',
    f_pending: '待审',
    f_approved: '已通过',
    f_rejected: '已驳回',
    f_all: '全部',
    empty_queue: '空队列——从右边提交第一条吧。',
    empty_detail: '左侧选一条查看链路 / 人审。',
    form_title: '提交审核',
    form_title_ph: '标题',
    form_body_ph: '正文',
    btn_submit: '提交',
    btn_submitting: '判定中…',
    btn_approve: '通过',
    btn_reject: '驳回',
    toast_pending: '已提交，转人工',
    toast_approved: '已提交，自动通过',
    toast_rejected: '已提交，自动驳回',
    toast_done_approve: '已通过',
    toast_done_reject: '已驳回',
    done_approve: '通过',
    done_reject: '驳回',
    by: 'by',
    lamp_off: '后端失联',
    lamp_ok: 'Laya 在线',
    lamp_degraded: 'heuristic 兜底',
    recent_latency: '最近判定',
    ms: 'ms',
    c_pending: '待审',
    c_approved: '通过',
    c_rejected: '驳回',
    c_today: '今日',
    err_backend: '后端未连接（先跑 ./start.sh），5 秒后重试。',
    tl_submit: '提交',
    tl_route: '路由',
    tl_decide: '判定',
    tl_gateway: '网关',
    tl_final: '终态',
    via_auto: '自动放行（置信度过线）',
    via_to_human: '转人工',
    waiting_human: '等待人工',
    no_route: 'heuristic（无路由）',
    route_missing: '路由信息缺失',
    running: '模型推理中…',
    reasons_note: '以下为引擎原始输出：',
    kind_article: '文章',
    kind_comment: '评论',
    kind_product: '商品',
    kind_ticket: '工单',
    kind_expense: '报销',
    kind_other: '其他',
    samples_title: '示例一键填表（点选填入，确认后再提交）',
    btn_clear: '清空',
    batch_bar: '已选',
    batch_approve: '批量通过',
    batch_reject: '批量驳回',
    batch_done: '批量完成',
    no_title: '(无标题)',
    loading_body: '全文加载中…',
    body_failed: '（全文加载失败）',
    conf_label: '置信度',
    tab_detail: '详情',
    tab_submit: '提交',
    kind_all: '全部类型',
    doc_title: '清放行 Clearance｜中文后台审核网关',
  },
  en: {
    title: 'Clearance',
    titleEn: '清放行',
    sub: 'Review gateway for Chinese ops backoffices · gated + audited',
    f_pending: 'Pending',
    f_approved: 'Approved',
    f_rejected: 'Rejected',
    f_all: 'All',
    empty_queue: 'Empty queue — submit the first one on the right.',
    empty_detail: 'Pick an item on the left to inspect / review.',
    form_title: 'Submit for review',
    form_title_ph: 'Title',
    form_body_ph: 'Body',
    btn_submit: 'Submit',
    btn_submitting: 'Deciding…',
    btn_approve: 'Approve',
    btn_reject: 'Reject',
    toast_pending: 'Submitted, routed to human',
    toast_approved: 'Submitted, auto-approved',
    toast_rejected: 'Submitted, auto-rejected',
    toast_done_approve: 'Approved',
    toast_done_reject: 'Rejected',
    done_approve: 'approved',
    done_reject: 'rejected',
    by: 'by',
    lamp_off: 'Backend offline',
    lamp_ok: 'Laya online',
    lamp_degraded: 'heuristic fallback',
    recent_latency: 'Last decision',
    ms: 'ms',
    c_pending: 'Pending',
    c_approved: 'Approved',
    c_rejected: 'Rejected',
    c_today: 'Today',
    err_backend: 'Backend unreachable (run ./start.sh first), retrying in 5s.',
    tl_submit: 'Submit',
    tl_route: 'Route',
    tl_decide: 'Decide',
    tl_gateway: 'Gateway',
    tl_final: 'Outcome',
    via_auto: 'Auto-passed (confidence above bar)',
    via_to_human: 'Routed to human',
    waiting_human: 'Awaiting human',
    no_route: 'heuristic (no routing)',
    route_missing: 'routing info missing',
    running: 'Model inferring…',
    reasons_note: 'Raw engine output:',
    kind_article: 'Article',
    kind_comment: 'Comment',
    kind_product: 'Product',
    kind_ticket: 'Ticket',
    kind_expense: 'Expense',
    kind_other: 'Other',
    samples_title: 'Samples (click to fill, confirm before submit)',
    btn_clear: 'Clear',
    batch_bar: 'selected',
    batch_approve: 'Approve selected',
    batch_reject: 'Reject selected',
    batch_done: 'Batch done',
    no_title: '(untitled)',
    loading_body: 'Loading full text…',
    body_failed: '(failed to load full text)',
    conf_label: 'confidence',
    tab_detail: 'Detail',
    tab_submit: 'Submit',
    kind_all: 'All kinds',
    doc_title: 'Clearance｜Chinese Review Gateway',
  },
} as const

export type StrKey = keyof (typeof DICT)['zh']

const LS_KEY = 'clearance-lang'

export function detectLang(): Lang {
  try {
    const saved = localStorage.getItem(LS_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    /* 无存储则按浏览器 */
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language || '' : ''
  return nav.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

export const LangCtx = React.createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: 'zh',
  setLang: () => {},
})

export function useT(): (key: StrKey) => string {
  const { lang } = React.useContext(LangCtx)
  return (key: StrKey) => DICT[lang][key] ?? DICT.zh[key] ?? key
}

export function useLang(): [Lang, (l: Lang) => void] {
  const [lang, setLangState] = React.useState<Lang>(detectLang)
  const setLang = (l: Lang) => {
    setLangState(l)
    try {
      localStorage.setItem(LS_KEY, l)
    } catch {
      /* 忽略 */
    }
    document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
  }
  return [lang, setLang]
}

export function stateName(lang: Lang, state: string): string {
  const map: Record<string, { zh: string; en: string }> = {
    pending: { zh: DICT.zh.f_pending, en: DICT.en.f_pending },
    approved: { zh: DICT.zh.f_approved, en: DICT.en.f_approved },
    rejected: { zh: DICT.zh.f_rejected, en: DICT.en.f_rejected },
  }
  return map[state]?.[lang] ?? state
}

export function kindName(lang: Lang, kind: string): string {  const map: Record<Lang, Record<string, string>> = {
    zh: {
      article: DICT.zh.kind_article,
      comment: DICT.zh.kind_comment,
      product: DICT.zh.kind_product,
      ticket: DICT.zh.kind_ticket,
      expense: DICT.zh.kind_expense,
      other: DICT.zh.kind_other,
    },
    en: {
      article: DICT.en.kind_article,
      comment: DICT.en.kind_comment,
      product: DICT.en.kind_product,
      ticket: DICT.en.kind_ticket,
      expense: DICT.en.kind_expense,
      other: DICT.en.kind_other,
    },
  }
  return map[lang][kind] ?? kind
}
