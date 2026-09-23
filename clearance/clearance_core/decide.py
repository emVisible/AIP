"""决策引擎：优先 Laya sidecar（HTTP），缺席诚实降级 heuristic。

Laya 答案格式：
  choice → answers[q]["choice"], answers[q]["confidence"]
  score  → answers[q]["score"]
  noul   → answers[q]["noul"]  (P(true) ∈ [0,1])

本文件保持 stdlib only：laya/torch 重依赖只活在 laya_sidecar 进程里。
"""
from __future__ import annotations

import json
import os
import urllib.request

from .models import AUTO_APPROVE, AUTO_REJECT, NEEDS_REVIEW, Decision, ReviewItem
from .questions import build_review_questions

AUTO_THRESHOLD = 0.85


def _sidecar_url() -> str:
    return os.environ.get("LAYA_SIDECAR_URL", "http://127.0.0.1:8685")


def _sidecar_timeout() -> float:
    return float(os.environ.get("LAYA_SIDECAR_TIMEOUT", "5"))

SPAM_HITS = ("中奖", "免费领取", "点击链接", "刷单", "兼职日结", "加微信",
             "free money", "click here", "winner", "crypto giveaway")
TOXIC_HITS = ("傻逼", "去死", "垃圾", "废物", "杀了你", "stupid", "kill you")
FRAUD_HITS = ("银行转账", "验证码", "中奖税", "保证金", "解冻费", "verify account",
              "suspended", "wire transfer")
SENSITIVE_HITS = ("密码", "身份证", "银行卡", "翻墙", "password", "ssn")


def _post(path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        _sidecar_url() + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(path: str, timeout: float) -> dict:
    with urllib.request.urlopen(_sidecar_url() + path, timeout=timeout) as r:
        return json.load(r)


def _hits(text: str, words) -> list:
    return [w for w in words if w in text]


def heuristic_decide(item: ReviewItem) -> Decision:
    """关键词兜底：信号弱，confidence 天花板 0.88，且只在命中明确时给过线值。"""
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
                    ["heuristic: no hits (weak signal, start sidecar for Laya)"], "L1")


def sidecar_decide(item: ReviewItem, questions: dict | None = None) -> Decision:
    res = _post("/decide", {"kind": item.kind, "text": item.text,
                            "lang_guess": (item.meta or {}).get("lang"),
                            "questions": questions or build_review_questions()},
                _sidecar_timeout())
    if not res.get("ok"):
        raise RuntimeError(f"sidecar error: {res.get('error')}")
    ans = res.get("answers", {})
    routing = res.get("routing", {})
    latency = res.get("latency_ms", -1)
    route_model = routing.get("model", "")
    reasons = [f"laya via sidecar model={route_model} {latency}ms"]
    if res.get("calibrated"):
        reasons.append("note: temperature fitted on held-out samples")
    else:
        reasons.append("note: confidence uncalibrated until temperature fit")

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
        return Decision(AUTO_REJECT, max(p_fraud, p_toxic), "laya:sidecar",
                        reasons + [f"fraud={p_fraud:.2f} toxic={p_toxic:.2f}"], "L2",
                        latency, route_model)
    if p_spam >= AUTO_THRESHOLD:
        return Decision(AUTO_REJECT, p_spam, "laya:sidecar",
                        reasons + [f"spam={p_spam:.2f}"], "L2",
                        latency, route_model)
    if p_sens >= 0.5 or sev >= 1.5 or cat in ("sensitive", "fraud", "abuse"):
        conf = max(p_sens, min(sev / 2.0, 1.0), cat_conf)
        return Decision(NEEDS_REVIEW, conf, "laya:sidecar",
                        reasons + [f"sensitive={p_sens:.2f} severity={sev:.2f}"], "L1",
                        latency, route_model)
    return Decision(AUTO_APPROVE, max(cat_conf, 0.5), "laya:sidecar", reasons, "L1",
                    latency, route_model)


def decide(item: ReviewItem, questions: dict | None = None) -> Decision:
    try:
        return sidecar_decide(item, questions)
    except Exception as e:  # sidecar 缺席/失败不炸链，诚实降级
        d = heuristic_decide(item)
        d.reasons.append(f"sidecar unreachable, fallback: {type(e).__name__}")
        return d


def engine_name() -> str:
    try:
        h = _get("/health", timeout=0.3)
        return "laya:sidecar" if h.get("ok") else "heuristic"
    except Exception:
        return "heuristic"
