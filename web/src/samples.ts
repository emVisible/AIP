/** 示例预设：点击填表，人工确认后再提交（守确认门）。 */
export interface Sample {
  id: string
  kind: string
  title: { zh: string; en: string }
  body: { zh: string; en: string }
}

export const SAMPLES: Sample[] = [
  {
    id: 'notice',
    kind: 'article',
    title: { zh: '小区停水通知', en: 'Water outage notice' },
    body: {
      zh: '明早 8 点到 12 点停水维护，请提前储水。',
      en: 'Water supply maintenance tomorrow 8am–12pm. Please store water in advance.',
    },
  },
  {
    id: 'ads',
    kind: 'comment',
    title: { zh: '限时返利', en: 'Limited rebate' },
    body: {
      zh: '点击链接免费领取 888 元，刷单日结加微信。',
      en: 'Click to claim $888 free, part-time brushing orders, add WeChat for daily pay.',
    },
  },
  {
    id: 'abuse',
    kind: 'comment',
    title: { zh: '谩骂', en: 'Abuse' },
    body: {
      zh: '你这个垃圾小编，去死吧。',
      en: 'You garbage editor, go die.',
    },
  },
  {
    id: 'fraud',
    kind: 'comment',
    title: { zh: '紧急通知', en: 'Urgent notice' },
    body: {
      zh: '银行转账验证码，保证金解冻费，逾期起诉。',
      en: 'Bank transfer verification code, margin unfreezing fee, lawsuit if overdue.',
    },
  },
  {
    id: 'appeal',
    kind: 'article',
    title: { zh: '账号申诉', en: 'Account appeal' },
    body: {
      zh: '我的密码是 123456，请帮我找回账号。',
      en: 'My password is 123456, please help recover my account.',
    },
  },
]
