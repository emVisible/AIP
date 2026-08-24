"""apa-core: 意图编译场景模板库（Phase B 策略一）。

TEMPLATE_REGISTRY：id → {keywords, slots, description, yaml}
yaml 中 {{slot}} 占位符由 LLM 填充；未填槽位转澄清问题。
"""
from __future__ import annotations

from typing import Any, Dict

TEMPLATE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "price-monitor": {
        "description": "定时抓取竞品/自家页面价格，超阈值预警",
        "keywords": ["价格", "监控", "竞品", "比价", "预警", "涨价"],
        "slots": ["url", "threshold", "notify_to"],
        "yaml": """process:
  id: price_monitor_draft
  mode: process
  trigger: { type: cron, expr: "0 9 * * *" }
  max_actions: 50
  steps:
    - id: open
      action: browser.navigate
      params: { url: "{{url}}" }
    - id: scrape
      action: browser.extract_table
      params:
        row_selector: "table tr"
        columns:
          name: ".name"
          price: ".price"
    - id: filter_high
      action: data.filter
      params:
        source: "{{steps.scrape.rows}}"
        column: price
        op: ">"
        value: "{{threshold}}"
    - id: alert
      action: email.send
      params:
        to: "{{notify_to}}"
        subject: "价格预警：{{steps.filter_high.count}} 项超标"
        body: "详见运行记录"
""",
    },
    "cs-quality-check": {
        "description": "拉取客服邮件会话，LLM 分类情绪，汇总日报",
        "keywords": ["客服", "质检", "聊天", "分类", "情绪", "会话"],
        "slots": ["imap_host", "imap_user"],
        "yaml": """process:
  id: cs_quality_draft
  mode: process
  trigger: { type: manual }
  max_actions: 100
  steps:
    - id: fetch
      action: email.receive
      params:
        host: "{{imap_host}}"
        username: "{{imap_user}}"
        criteria: UNSEEN
        limit: 20
    - id: classify_loop
      type: foreach
      params:
        source: "{{steps.fetch.messages}}"
        item_var: mail
        body_action: llm.text
        body_params:
          task: classify
          input: "{{mail.text}}"
          labels: ["咨询", "投诉", "好评"]
""",
    },
}


def merged_with(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """允许测试/用户目录覆盖内置模板。"""
    out = dict(TEMPLATE_REGISTRY)
    out.update(overrides)
    return out
