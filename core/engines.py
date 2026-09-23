"""Engine 插槽：Decision Engine 可替换（AIP C1 的灵魂）。

Laya 只是其中一个可替换引擎，网关才是主人。级联顺序默认成本优先：
    rules → laya:sidecar → jev → heuristic
环境变量 ENGINE_ORDER 可覆写（逗号分隔）。任一引擎缺席/故障自动跳过，
heuristic 永远在线兜底——级联永不抛错（返回 Decision 或 human）。
"""
from __future__ import annotations

import json
import os
import urllib.request

from .calibration import load_table, rescale_answers
from .models import AUTO_APPROVE, AUTO_REJECT, NEEDS_REVIEW, Decision, ReviewItem
from .questions import build_review_questions

AUTO_THRESHOLD = 0.85
DEFAULT_ORDER = ("rules", "laya:sidecar", "jev", "heuristic")

_CRED_RULE = ("密码", "身份证", "银行卡", "password", "ssn")


class EngineUnavailable(Exception):
    """引擎缺席（无 key / 进程不在 / 超时），级联继续下一引擎。"""


class Engine:
    name = "base"

    def decide(self, item: ReviewItem, questions: dict | None = None):
        """返回 Decision；返回 None 表示弃权（静默过号）。"""
        raise NotImplementedError


def map_typed_answers(ans: dict, *, engine: str, latency_ms: int = -1,
                      route_model: str = "", usage: dict | None = None,
                      calibrated: bool = False) -> Decision:
    """laya/jev 同构答案 → Decision（两家 schema 一致，映射只写一次）。"""
    reasons = [f"{engine} model={route_model} {latency_ms}ms".strip()]
    reasons.append("note: temperature fitted on held-out samples" if calibrated
                   else "note: confidence uncalibrated until temperature fit")

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
    reasons.append(f"{engine} category={cat} conf={cat_conf:.2f}")
    p_fraud, p_toxic = noul("fraud"), noul("toxic")
    p_spam, p_sens = noul("is_spam"), noul("sensitive")
    sev = score("severity")
    kw = dict(latency_ms=latency_ms, route_model=route_model,
              usage=usage or {})

    if max(p_fraud, p_toxic) >= AUTO_THRESHOLD:
        return Decision(AUTO_REJECT, max(p_fraud, p_toxic), engine,
                        reasons + [f"fraud={p_fraud:.2f} toxic={p_toxic:.2f}"],
                        "L2", **kw)
    if p_spam >= AUTO_THRESHOLD:
        return Decision(AUTO_REJECT, p_spam, engine,
                        reasons + [f"spam={p_spam:.2f}"], "L2", **kw)
    if p_sens >= 0.5 or sev >= 1.5 or cat in ("sensitive", "fraud", "abuse"):
        conf = max(p_sens, min(sev / 2.0, 1.0), cat_conf)
        return Decision(NEEDS_REVIEW, conf, engine,
                        reasons + [f"sensitive={p_sens:.2f} severity={sev:.2f}"],
                        "L1", **kw)
    return Decision(AUTO_APPROVE, max(cat_conf, 0.5), engine, reasons, "L1", **kw)


class RulesEngine(Engine):
    """确定性规则（零模型，AIP Zero-LLM 第一级）：高精度窄规则，不中即弃权。"""
    name = "rules"

    def decide(self, item: ReviewItem, questions: dict | None = None):
        text = item.text
        if any(w in text for w in _CRED_RULE):
            return Decision(NEEDS_REVIEW, 0.75, "rules",
                            ["rules: credential-like content, must human review"], "L1")
        return None


class HeuristicEngine(Engine):
    """关键词兜底（永远在线，级联末位）。"""
    name = "heuristic"

    def decide(self, item: ReviewItem, questions: dict | None = None):
        return heuristic_decide(item)


def _sidecar_url() -> str:
    return os.environ.get("LAYA_SIDECAR_URL", "http://127.0.0.1:8685")


def _sidecar_timeout() -> float:
    # 冷启动/MPS 首推可达数秒，前端有 running 脉冲兜住等待体验
    return float(os.environ.get("LAYA_SIDECAR_TIMEOUT", "15"))


class LayaSidecarEngine(Engine):
    """自托管 Laya（$0）：经 sidecar HTTP 调用，缺席抛 EngineUnavailable。"""
    name = "laya:sidecar"

    def decide(self, item: ReviewItem, questions: dict | None = None):
        import time
        payload = {"kind": item.kind, "text": item.text,
                   "lang_guess": (item.meta or {}).get("lang"),
                   "questions": questions or build_review_questions()}
        req = urllib.request.Request(
            _sidecar_url() + "/decide", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=_sidecar_timeout()) as r:
                res = json.load(r)
        except Exception as e:
            raise EngineUnavailable(f"sidecar unreachable: {type(e).__name__}")
        if not res.get("ok"):
            raise EngineUnavailable(f"sidecar error: {res.get('error')}")
        return map_typed_answers(
            res.get("answers", {}), engine="laya:sidecar",
            latency_ms=res.get("latency_ms", int((time.time() - t0) * 1000)),
            route_model=(res.get("routing") or {}).get("model", ""),
            calibrated=bool(res.get("calibrated")))


def _jev_api_url() -> str:
    return os.environ.get("JEV_API_URL", "https://api.typesafe.ai")


def _jev_timeout() -> float:
    return float(os.environ.get("JEV_TIMEOUT", "10"))


class JevEngine(Engine):
    """TypeSafe Jev（云端付费 API）：无 key 自动跳过，裸 urllib（stdlib 纯洁）。"""
    name = "jev"

    def decide(self, item: ReviewItem, questions: dict | None = None):
        import time
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            raise EngineUnavailable("no TYPESAFE_API_KEY")
        payload = {"model": os.environ.get("JEV_MODEL", "jev-latest"),
                   "state": {"kind": item.kind, "text": item.text},
                   "questions": questions or build_review_questions()}
        req = urllib.request.Request(
            _jev_api_url() + "/v1/systemone", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"}, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=_jev_timeout()) as r:
                res = json.load(r)
        except Exception as e:
            raise EngineUnavailable(f"jev unreachable: {type(e).__name__}")
        table = load_table(os.environ.get("JEV_CALIBRATION_FILE", "") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "eval", "calibration.jev.json"))
        answers, calibrated = rescale_answers(res.get("answers", {}), table)
        return map_typed_answers(
            answers, engine="jev",
            latency_ms=int((time.time() - t0) * 1000),
            route_model=res.get("model", ""),
            usage=dict(res.get("usage") or {}),
            calibrated=calibrated)


_REGISTRY: dict = {}


def register(engine: Engine) -> None:
    _REGISTRY[engine.name] = engine


for _e in (RulesEngine(), LayaSidecarEngine(), JevEngine(), HeuristicEngine()):
    register(_e)


def get(name: str) -> Engine:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown engine: {name} (known: {sorted(_REGISTRY)})")


def order() -> list:
    return [s.strip() for s in
            os.environ.get("ENGINE_ORDER", ",".join(DEFAULT_ORDER)).split(",")
            if s.strip()]


def cascade(item: ReviewItem, questions: dict | None = None,
            order_names: list | None = None) -> Decision:
    """按序尝试：首个 Decision 胜出；弃权静默过号；故障记 reason 后继续。"""
    skipped: list[str] = []
    names = order_names or order()
    for name in names:
        try:
            engine = get(name)
        except ValueError:
            skipped.append(f"{name}: unknown engine")
            continue
        try:
            d = engine.decide(item, questions)
        except EngineUnavailable as e:
            skipped.append(f"{name}: {e}")
            continue
        if d is None:
            continue
        if skipped:
            d.reasons = [f"skipped: {'; '.join(skipped)}"] + d.reasons
        return d
    # unreachable：heuristic 永远在线；防御性回退
    return heuristic_decide(item)


def availability() -> dict:
    """各引擎可用性 + 主模型引擎（状态栏/统计用，不跑推理）。"""
    names = order()
    avail = ["rules", "heuristic"]
    try:
        with urllib.request.urlopen(_sidecar_url() + "/health", timeout=0.3) as r:
            if json.load(r).get("ok"):
                avail.append("laya:sidecar")
    except Exception:
        pass
    if os.environ.get("TYPESAFE_API_KEY", ""):
        avail.append("jev")
    primary = next((n for n in ("laya:sidecar", "jev") if n in avail), "heuristic")
    return {"order": names, "available": [n for n in names if n in avail],
            "primary": primary}


SPAM_HITS = ("中奖", "免费领取", "点击链接", "刷单", "兼职日结", "加微信",
             "free money", "click here", "winner", "crypto giveaway")
TOXIC_HITS = ("傻逼", "去死", "垃圾", "废物", "杀了你", "stupid", "kill you")
FRAUD_HITS = ("银行转账", "验证码", "中奖税", "保证金", "解冻费", "verify account",
              "suspended", "wire transfer")
SENSITIVE_HITS = ("密码", "身份证", "银行卡", "翻墙", "password", "ssn")


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
