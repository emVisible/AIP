"""apa-sdk: 自愈与熔断（设计文档 §11）。

三层自愈：
  第一层 Executor 级（毫秒级，不消耗 AIP seq）——本模块 ResilientExecutor
  第二层 Gateway 级（秒级）——RetryScheduler（apa_core.gateway）
  第三层 Decision Engine 级（分钟级）——规则引擎的重试策略
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from .executor_base import AIPExecutor


class ExecutorCircuitBreaker:
    """CLOSED → OPEN（连续失败 ≥ 阈值）→ HALF_OPEN（等待超时后）→ CLOSED（§11.3）。"""

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT_S = 60

    def __init__(
        self,
        target: str,
        *,
        failure_threshold: int = FAILURE_THRESHOLD,
        recovery_timeout_s: int = RECOVERY_TIMEOUT_S,
    ) -> None:
        self.target = target
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.state = "CLOSED"
        self.failure_count = 0
        self.opened_at = 0.0

    def before_action(self) -> None:
        if self.state == "OPEN":
            if time.monotonic() - self.opened_at > self.recovery_timeout_s:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError(f"circuit OPEN for {self.target}")

    def on_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def on_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = time.monotonic()


class CircuitOpenError(Exception):
    pass


class ResilientExecutor(AIPExecutor):
    """针对已知瞬时错误在 Executor 内部重试，不产生额外 AIP 消息（§11.2 第一层）。

    transient_check: (name, params, exc) -> bool，判断错误是否可本地重试。
    """

    def __init__(self, *args, transient_check: Optional[Callable] = None,
                 max_attempts: int = 2, **kw) -> None:
        super().__init__(*args, **kw)
        self.transient_check = transient_check or (
            lambda name, params, exc: isinstance(
                exc, (ElementNotInteractable, PageNotReady)))
        self.max_attempts = max_attempts
        self.circuit_breakers: dict = {}

    def breaker_for(self, target: str) -> ExecutorCircuitBreaker:
        if target not in self.circuit_breakers:
            self.circuit_breakers[target] = ExecutorCircuitBreaker(target)
        return self.circuit_breakers[target]

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        target = params.get("target") or name
        breaker = self.breaker_for(target)
        breaker.before_action()
        for attempt in range(self.max_attempts + 1):
            try:
                result = self._real_execute(name, params)
                breaker.on_success()
                return result
            except (ElementNotInteractable, PageNotReady) as e:
                if attempt < self.max_attempts:
                    time.sleep(0.05 * (attempt + 1))
                    self._wait_for_stable_state()
                    continue
                breaker.on_failure()
                return False, {"code": type(e).__name__,
                               "retry": {"allowed": True, "after_ms": 1000}}
        return False, {"code": "internal_error"}

    def _real_execute(self, name: str, params: dict) -> Tuple[bool, dict]:
        raise NotImplementedError

    def _wait_for_stable_state(self) -> None:
        """子类可覆盖（如等待页面 networkidle）。"""


class ElementNotInteractable(Exception):
    pass


class PageNotReady(Exception):
    pass