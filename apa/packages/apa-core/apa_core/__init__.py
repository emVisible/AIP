"""apa-core — APA 协议层核心（设计文档 §8/§9/§10/§12）。"""

from .audit import AuditService
from .context import APAContextStore, ContextRefError
from .embedded import EmbeddedGateway
from .gateway import APAGateway, MAX_EVENT_DATA_BYTES, RetryScheduler
from .policy import PolicyConfig, PolicyDecision
from .registry import (
    RISK_LEVELS,
    ActionRegistry,
    RegistryEntry,
    RegistryError,
    load_registries,
)
from .rules import RuleBasedAgent, RuleEngine, interpolate
from .session import IllegalStateTransition, SessionStateMachine, SessionRecord

__all__ = [
    "APAGateway",
    "APAContextStore",
    "ActionRegistry",
    "AuditService",
    "ContextRefError",
    "EmbeddedGateway",
    "IllegalStateTransition",
    "MAX_EVENT_DATA_BYTES",
    "PolicyConfig",
    "PolicyDecision",
    "RISK_LEVELS",
    "RegistryEntry",
    "RegistryError",
    "RetryScheduler",
    "RuleBasedAgent",
    "RuleEngine",
    "SessionRecord",
    "SessionStateMachine",
    "interpolate",
    "load_registries",
]

__version__ = "0.1.0"