"""最小校验链（AIP §8.3 的网关思想，单文件实现）。

顺序：Registry ∈ 检查 → C4 凭据扫描 → 置信度/风险门控 → 审计。
幻觉动作名在此被拒绝（∉Registry 即 rejected），这是反玩具的核心。
"""
from __future__ import annotations

import json
import re
from time import time

from .decide import AUTO_THRESHOLD
from .models import AUTO_APPROVE, AUTO_REJECT, NEEDS_REVIEW

# C3：幂等/risk 只在此声明，消息里不许带。
REGISTRY = {
    "context.get": {"risk": "L0", "idempotency": "required"},
    "session.complete": {"risk": "L0", "idempotency": "required"},
    "review.defer": {"risk": "L1", "idempotency": "required"},
    "human.task.create": {"risk": "L1", "idempotency": "required"},
    "review.approve": {"risk": "L2", "idempotency": "required"},
    "review.reject": {"risk": "L2", "idempotency": "required"},
    "notify.send": {"risk": "L2", "idempotency": "required"},
}

# C4：凭据禁入 payload。L3/L4 本网关不存在，出现即转人工。
_CRED_RE = re.compile(
    r"(password|passwd|pwd|api[_-]?key|secret|token|身份证|银行卡|-----BEGIN )",
    re.IGNORECASE,
)


def validate_action(name: str, params: dict) -> tuple[bool, str]:
    if name not in REGISTRY:
        return False, f"action_not_registered: {name}"
    blob = json.dumps(params, ensure_ascii=False, default=str)
    if len(blob) > 4096:  # CoD-1：事件/参数体 ≤4KB
        return False, "payload_too_large: >4KB, use context.get"
    if _CRED_RE.search(blob):
        return False, "credential_in_payload: C4 violation"
    return True, "permitted"


def route(action: str, confidence: float) -> tuple[str, str]:
    """置信度门控：自动动作必须过线，否则一律转人工。"""
    if action in (AUTO_APPROVE, AUTO_REJECT):
        if confidence >= AUTO_THRESHOLD:
            return action, "auto"
        return NEEDS_REVIEW, f"low_confidence {confidence:.2f}<{AUTO_THRESHOLD}"
    return NEEDS_REVIEW, "policy_default"


def audit_log(path: str, event: dict) -> None:
    event = {"ts": int(time() * 1000), **event}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
