"""apa-core — APA 协议层核心（设计文档 §8/§9/§10/§12）。"""

from .audit import AuditService
from .cascade import CascadingAgent
from .context import APAContextStore, ContextRefError
from .embedded import EmbeddedGateway
from .gateway import APAGateway, MAX_EVENT_DATA_BYTES, RetryScheduler
from .human_loop import HumanTaskManager
from .llm import FakeLLMClient, LLMClient, LLMError, parse_decision
from .persist import SessionJournal, load_journal, recover, release_expired
from .policy import PolicyConfig, PolicyDecision
from .process import (
    ProcessDef,
    ProcessDefinitionError,
    ProcessEngine,
    ProcessRun,
    build_process,
    load_process,
)
from .registry import (
    RISK_LEVELS,
    ActionRegistry,
    RegistryEntry,
    RegistryError,
    load_registries,
)
from .rules import RuleBasedAgent, RuleEngine, interpolate
from .sequence_compat import RecoverableReceiver
from .session import IllegalStateTransition, SessionStateMachine, SessionRecord

__all__ = [
    "APAGateway",
    "APAContextStore",
    "ActionRegistry",
    "AuditService",
    "CascadingAgent",
    "ContextRefError",
    "EmbeddedGateway",
    "FakeLLMClient",
    "HumanTaskManager",
    "IllegalStateTransition",
    "LLMClient",
    "LLMError",
    "MAX_EVENT_DATA_BYTES",
    "PolicyConfig",
    "PolicyDecision",
    "ProcessDef",
    "ProcessDefinitionError",
    "ProcessEngine",
    "ProcessRun",
    "RISK_LEVELS",
    "RecoverableReceiver",
    "RegistryEntry",
    "RegistryError",
    "RetryScheduler",
    "RuleBasedAgent",
    "RuleEngine",
    "SessionJournal",
    "SessionRecord",
    "SessionStateMachine",
    "interpolate",
    "load_registries",
    "load_journal",
    "build_process",
    "load_process",
    "parse_decision",
    "recover",
    "release_expired",
]

__version__ = "0.3.0"