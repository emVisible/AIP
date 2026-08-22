"""apa-sdk — 开发者 SDK（设计文档 §14）。"""

from .coalescer import EventCoalescer, SyncCoalescer
from .composite import CompositeExecutor
from .executor_base import AIPExecutor, ExecutorPreconditionError
from .recorder import SchemaRecorder
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
from .vision import (
    FakeVisionAdapter,
    OpenAICompatibleVisionAdapter,
    VisionAdapter,
    VisionError,
    parse_vision_elements,
)

__all__ = [
    "AIPExecutor",
    "CircuitOpenError",
    "CompositeExecutor",
    "Element",
    "ElementNotInteractable",
    "EventCoalescer",
    "ExecutorCircuitBreaker",
    "ExecutorPreconditionError",
    "PageNotReady",
    "ResilientExecutor",
    "SchemaRecorder",
    "ScreenState",
    "SemanticAdapter",
    "SemanticEvent",
    "SyncCoalescer",
    "FakeVisionAdapter",
    "OpenAICompatibleVisionAdapter",
    "VisionAdapter",
    "VisionError",
    "parse_currency",
    "parse_int",
    "parse_vision_elements",
]

__version__ = "0.2.0"