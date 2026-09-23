"""置信度温度校准：纯数学（stdlib），sidecar 与拟合脚本共用。

对 laya 三类答案的概率分布做温度缩放（temperature scaling）：
  choice/score：p' = softmax(log(p) / T)，重算 argmax/期望值
  noul：二分类，logit 缩放后 sigmoid

拟合目标：持出样本上的 NLL 最小（网格搜索，无需 scipy）。
T=1.0 恒为候选，保证拟合永不差于出厂。
"""
from __future__ import annotations

import json
import math

_EPS = 1e-9
_GRID = [round(0.1 + 0.05 * i, 2) for i in range(99)]  # 0.10..5.00


def _clip(p: float) -> float:
    return min(1.0 - _EPS, max(_EPS, p))


def _softmax(logits: list) -> list:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    s = sum(exps)
    return [e / s for e in exps]


def scale_categorical(probs: dict, true_label: str, T: float) -> tuple[dict, float]:
    """返回 (缩放后分布, NLL)。true_label 仅用于算 NLL，不参与缩放。"""
    keys = list(probs.keys())
    scaled = _softmax([math.log(_clip(probs[k])) / T for k in keys])
    out = dict(zip(keys, scaled))
    nll = -math.log(_clip(out.get(true_label, _EPS)))
    return out, nll


def scale_binary(p: float, T: float) -> float:
    logit = math.log(_clip(p) / _clip(1.0 - p))
    return 1.0 / (1.0 + math.exp(-logit / T))


def nll_binary(pairs: list, T: float) -> float:
    """pairs: [(p, y_middle)]. y∈{0,1}。"""
    nll = 0.0
    for p, y in pairs:
        q = _clip(scale_binary(p, T))
        nll += -(y * math.log(q) + (1 - y) * math.log(1 - q))
    return nll / max(1, len(pairs))


def fit_temperature_binary(pairs: list) -> tuple[float, float, float]:
    """返回 (最佳T, 拟合前NLL, 拟合后NLL)。样本不足返回 (1.0, nll, nll)。"""
    if not pairs or not any(y == 1 for _, y in pairs) or not any(y == 0 for _, y in pairs):
        base = nll_binary(pairs, 1.0) if pairs else 0.0
        return 1.0, base, base
    base = nll_binary(pairs, 1.0)
    best_T, best = 1.0, base
    for T in _GRID:
        v = nll_binary(pairs, T)
        if v < best:
            best_T, best = T, v
    return best_T, base, best


def fit_temperature_categorical(rows: list) -> tuple[float, float, float]:
    """rows: [(probs_dict, true_label)]。"""
    if not rows:
        return 1.0, 0.0, 0.0

    def nll(T: float) -> float:
        return sum(scale_categorical(p, t, T)[1] for p, t in rows) / len(rows)

    base = nll(1.0)
    best_T, best = 1.0, base
    for T in _GRID:
        v = nll(T)
        if v < best:
            best_T, best = T, v
    return best_T, base, best


def rescale_answer(ans: dict, T: float) -> dict:
    """按拟合温度重算单个答案；T==1.0 原样返回。未知形状原样返回。"""
    if T == 1.0 or not isinstance(ans, dict):
        return ans
    t = ans.get("type")
    try:
        if t == "noul":
            p = float(ans.get("noul", 0.5))
            out = dict(ans)
            q = scale_binary(p, T)
            out["noul"] = q
            out["confidence"] = max(q, 1 - q)
            return out
        if t in ("choice", "score") and isinstance(ans.get("probabilities"), dict):
            probs = {str(k): float(v) for k, v in ans["probabilities"].items()}
            keys = list(probs.keys())
            scaled = _softmax([math.log(_clip(probs[k])) / T for k in keys])
            out = dict(ans)
            out["probabilities"] = dict(zip(keys, scaled))
            if t == "choice":
                top = max(range(len(keys)), key=lambda i: scaled[i])
                out["choice"] = keys[top]
                out["confidence"] = scaled[top]
            else:
                out["score"] = sum(float(keys[i]) * scaled[i] for i in range(len(keys)))
                out["confidence"] = max(scaled)
            return out
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return ans


def rescale_answers(answers: dict, table: dict) -> tuple[dict, bool]:
    """table: {qid: {T: float}}。返回 (新answers, 是否有任一生效)。"""
    if not table:
        return answers, False
    out, applied = dict(answers), False
    for qid, entry in table.items():
        T = float((entry or {}).get("T", 1.0))
        if qid in out and T != 1.0:
            out[qid] = rescale_answer(out[qid], T)
            applied = True
    return out, applied


def load_table(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
