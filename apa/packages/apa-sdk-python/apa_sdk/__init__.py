"""apa-sdk — 开发者 SDK（设计文档 §14）。"""

from .coalescer import EventCoalescer, SyncCoalescer
from .executor_base import AIPExecutor, ExecutorPreconditionError
from .resilient import (
    CircuitOpenError,
    ElementNotInteractable,
    ExecutorCircuitBreaker,
    PageNotReady,
    ResilientExecutor,
)
from .semantic_adapter import (
    Element,
    ScreenState,
    SemanticAdapter,
    SemanticEvent,
    parse_currency,
    parse_int,
)

__all__ = [
    "AIPExecutor",
    "CircuitOpenError",
    "Element",
    "ElementNotInteractable",
    "EventCoalescer",
    "ExecutorCircuitBreaker",
    "ExecutorPreconditionError",
    "PageNotReady",
    "ResilientExecutor",
    "ScreenState",
    "SemanticAdapter",
    "SemanticEvent",
    "SyncCoalescer",
    "parse_currency",
    "parse_int",
]

__version__ = "0.1.0"