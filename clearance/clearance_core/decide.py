"""决策引擎：有 laya 走 Router 单次前向，无则 heuristic（诚实标注引擎名）。

Laya 答案格式（见 laya/README）：
  choice → answers[q]["choice"], answers[q]["confidence"]
  score  → answers[q]["score"]
  noul   → answers[q]["noul"]  (P(true) ∈ [0,1])
"""
from __future__ import annotations

import importlib.util

from .models import AUTO_APPROVE, AUTO_REJECT, NEEDS_REVIEW, Decision, ReviewItem
from .questions import build_review_questions

AUTO_THRESHOLD = 0.85

SPAM_HITS = ("中奖", "免费领取", "点击链接", "刷单", "兼职日结", "加微信",
             "free money", "click here", "winner", "crypto giveaway")
TOXIC_HITS = ("傻逼", "去死", "垃圾", "废物", "杀了你", "stupid", "kill you")
FRAUD_HITS = ("银行转账", "验证码", "中奖税", "保证金", "解冻费", "verify account",
              "suspended", "wire transfer")
SENSITIVE_HITS = ("密码", "身份证", "银行卡", "翻墙", "password", "ssn")

_LAYA_ROUTER = None
_LAYA_OK = importlib.util.find_spec("laya") is not None


def _get_router():
    global _LAYA_ROUTER
    if _LAYA_ROUTER is None:
        from laya import Router
        _LAYA_ROUTER = Router(max_loaded=2)
    return _LAYA_ROUTER


def _hits(text: str, words) -> list:
    return [w for w in words if w in text]


def heuristic_decide(item: ReviewItem) -> Decision:
    """关键词兜底：信号弱，confidence 天花板 0.86 且只在零命中时给过线值。"""
    text = item.text
    reasons: list[str] = []
    spam = _hits(text, SPAM_HITS)
    toxic = _hits(text, TOXIC_HITS)
    fraud = _hits(text, FRAUD_HITS)
    sens = _hits(text, SENSITIVE_HITS)

    if fraud or toxic:
        reasons += [f"heuristic hit fraud={fraud}", f"heuristic hit toxic={toxic}"]
        return Decision(AUTO_REJECT, 0.88, "heuristic", reasons, "L2")
    if spam:
        reasons.append(f"heuristic hit spam={spam}")
        return Decision(AUTO_REJECT, 0.86, "heuristic", reasons, "L2")
    if sens:
        reasons.append(f"heuristic hit sensitive={sens}")
        return Decision(NEEDS_REVIEW, 0.70, "heuristic", reasons, "L1")
    if len(text) > 4000:
        return Decision(NEEDS_REVIEW, 0.60, "heuristic",
                        ["heuristic: text too long for weak signal"], "L1")
    return Decision(AUTO_APPROVE, 0.86, "heuristic",
                    ["heuristic: no hits (weak signal, replace with Laya)"], "L1")


def laya_decide(item: ReviewItem, questions: dict | None = None) -> Decision:
    router = _get_router()
    questions = questions or build_review_questions()
    res = router.predict({"kind": item.kind, "text": item.text}, questions)
    ans = res.get("answers", {})
    reasons: list[str] = []

    def noul(q: str) -> float:
        try:
            return float(ans.get(q, {}).get("noul", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def choice(q: str):
        a = ans.get(q, {})
        return a.get("choice", "other"), float(a.get("confidence", 0.0) or 0.0)

    def score(q: str) -> float:
        try:
            return float(ans.get(q, {}).get("score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    cat, cat_conf = choice("category")
    reasons.append(f"laya category={cat} conf={cat_conf:.2f}")
    p_fraud, p_toxic = noul("fraud"), noul("toxic")
    p_spam, p_sens = noul("is_spam"), noul("sensitive")
    sev = score("severity")

    if max(p_fraud, p_toxic) >= AUTO_THRESHOLD:
        return Decision(AUTO_REJECT, max(p_fraud, p_toxic), "laya",
                        reasons + [f"fraud={p_fraud:.2f} toxic={p_toxic:.2f}"], "L2")
    if p_spam >= AUTO_THRESHOLD:
        return Decision(AUTO_REJECT, p_spam, "laya",
                        reasons + [f"spam={p_spam:.2f}"], "L2")
    if p_sens >= 0.5 or sev >= 1.5 or cat in ("sensitive", "fraud", "abuse"):
        conf = max(p_sens, min(sev / 2.0, 1.0), cat_conf)
        return Decision(NEEDS_REVIEW, conf, "laya",
                        reasons + [f"sensitive={p_sens:.2f} severity={sev:.2f}"], "L1")
    return Decision(AUTO_APPROVE, max(cat_conf, 0.5), "laya", reasons, "L1")


def decide(item: ReviewItem, questions: dict | None = None) -> Decision:
    if _LAYA_OK:
        try:
            return laya_decide(item, questions)
        except Exception as e:  # 模型失败不炸链，诚实降级
            d = heuristic_decide(item)
            d.reasons.append(f"laya failed, fallback: {e}")
            return d
    return heuristic_decide(item)


def engine_name() -> str:
    return "laya" if _LAYA_OK else "heuristic"
