"""通用 6 问：Laya typed-decision 格式（choice / score / noul）。

与 laya/presets.py（triage/email/guard/moderation）同构，但收敛为
审核网关固定 schema：category 可按业务配置，其余 5 个是网关不变量。
约束前置：choice 选项 ≤8（>20 必须走 predict_shortlist）；score 只用 3 档。
"""
from __future__ import annotations


DEFAULT_CATEGORIES = {
    "normal": "普通合规内容，可直接通过",
    "ads": "营销推广、引流、联系方式",
    "abuse": "辱骂、人身攻击、仇恨言论",
    "fraud": "诈骗、钓鱼、虚假中奖、刷单兼职",
    "sensitive": "涉密、涉政、色情、血腥等敏感内容",
    "other": "以上都不属于",
}


def build_review_questions(categories: dict | None = None) -> dict:
    cats = categories or DEFAULT_CATEGORIES
    assert len(cats) <= 8, f"category 选项必须 ≤8，当前 {len(cats)}"
    return {
        "category": {
            "type": "choice",
            "instructions": "Which category does the submitted content in `text` belong to?",
            "criteria": dict(cats),
        },
        "is_spam": {
            "type": "noul",
            "instructions": "Is `text` unsolicited spam, ads, or promotion?",
        },
        "toxic": {
            "type": "noul",
            "instructions": "Is `text` toxic: rude, insulting, or likely to harass someone?",
        },
        "fraud": {
            "type": "noul",
            "instructions": "Is `text` fraud, phishing, or a scam to steal money or credentials?",
        },
        "sensitive": {
            "type": "noul",
            "instructions": "Does `text` contain sensitive content: credentials, personal data, or politically sensitive material?",
        },
        "severity": {
            "type": "score",
            "instructions": "How severe is any rule-breaking in `text`?",
            "criteria": [
                "none: ordinary compliant content",
                "mild: promotional tone or borderline, no target",
                "severe: fraud, abuse, or sensitive content",
            ],
        },
    }
