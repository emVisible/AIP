"""apa-core — APA 协议层核心（设计文档 §8/§9/§10/§12）。"""

from .audit import AuditService
from .analytics import report as analytics_report
from .analytics import summarize as analytics_summarize
from .cascade import CascadingAgent
from .context import APAContextStore, ContextRefError
from .cron import CronError, CronExpr, is_due as cron_is_due
from .embedded import EmbeddedGateway
from .gateway import APAGateway, MAX_EVENT_DATA_BYTES, RetryScheduler
from .human_loop import HumanTaskManager
from .launcher import ProcessRunner, run_process
from .llm import FakeLLMClient, LLMClient, LLMError, parse_decision
from .scheduler import Scheduler, SchedulerError
from .mock_erp import MockERP
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
from .vault import (
    EncryptedFileVault,
    HashiCorpVaultBackend,
    EnvVault,
    FernetBackend,
    VaultBackend,
    VaultError,
    VaultManager,
    open_vault,
)

__all__ = [
    "APAGateway",
    "APAContextStore",
    "ActionRegistry",
    "AuditService",
    "CascadingAgent",
    "ContextRefError",
    "CronExpr",
    "CronError",
    "EmbeddedGateway",
    "EncryptedFileVault",
    "EnvVault",
    "FakeLLMClient",
    "FernetBackend",
    "HashiCorpVaultBackend",
    "HumanTaskManager",
    "IllegalStateTransition",
    "LLMClient",
    "LLMError",
    "MAX_EVENT_DATA_BYTES",
    "MockERP",
    "PolicyConfig",
    "PolicyDecision",
    "ProcessRunner",
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
    "Scheduler",
    "SchedulerError",
    "SessionJournal",
    "SessionRecord",
    "SessionStateMachine",
    "VaultBackend",
    "VaultError",
    "VaultManager",
    "analytics_report",
    "analytics_summarize",
    "cron_is_due",
    "run_process",
    "interpolate",
    "load_registries",
    "load_journal",
    "build_process",
    "load_process",
    "open_vault",
    "parse_decision",
    "recover",
    "release_expired",
]

__version__ = "1.0.0"