"""APA Studio Protocol v1 —— 三端类型单源（H3 · harness-fusion 资产 #5）。

移植来源：OpenAI Codex `codex-rs/app-server-protocol`（Apache-2.0）的
消息分类学设计——request/response/notification 三态、item 粒度运行事件、
approval elicitation；TS 类型由本模块经 JSON Schema 单源生成
（见 studio_codegen.py，产物 frontend/src/shared/studioProtocol.ts）。

演进规则：
  - 只加不改：新字段必须可选/带默认；破坏性变更换方法名并升 PROTOCOL_VERSION
  - 方法命名 `<域>.<动作>`，与 REST 语义一一映射（适配层过渡期并存）
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1

# ---- 信封 ----------------------------------------------------------------------


class RpcRequest(BaseModel):
    """客户端 → 引擎。id 原样回带用于配对。"""
    id: str = Field(description="请求配对 id（uuid/自增均可）")
    method: str = Field(description="点分方法名，如 session.append")
    params: Dict[str, Any] = Field(default_factory=dict)


class RpcErrorBody(BaseModel):
    code: Literal[
        "method_not_found", "invalid_params", "not_found",
        "conflict", "internal_error",
    ]
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class RpcResponse(BaseModel):
    """引擎 → 客户端。ok=false 时 error 必填。"""
    id: str
    ok: bool
    result: Optional[Any] = None
    error: Optional[RpcErrorBody] = None


# ---- 领域载荷（request params / result 复用） ------------------------------------


class SessionEvent(BaseModel):
    """会话事件（sessions.py append 输出）。"""
    seq: int
    ts: float
    kind: str
    payload: Dict[str, Any]


class SessionAppendParams(BaseModel):
    sid: str
    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class SessionAppendResult(BaseModel):
    ok: bool
    event: SessionEvent


class SessionReadResult(BaseModel):
    id: str
    events: List[SessionEvent]
    view: List[Dict[str, Any]]


class SessionMeta(BaseModel):
    id: str
    events: int
    mtime: float
    bytes: int


class JobRecord(BaseModel):
    id: str
    kind: str
    owner_session: str
    status: Literal["running", "done", "cancelled"]
    created_at: float
    settled_at: Optional[float] = None
    result_ref: Optional[str] = None


# ---- Notification（引擎 → 客户端推送；传输层 H3-2 接线） -------------------------


class RunStepNotification(BaseModel):
    """item 粒度运行事件（对齐 codex item 事件）。"""
    session: str
    step_id: str
    action: str
    status: Literal["ok", "failed", "skipped"]
    ts: float
    spilled: bool = False


class RunOutcomeNotification(BaseModel):
    session: str
    outcome: str


class ApprovalElicitation(BaseModel):
    """审批引出（对齐 codex elicitation）——草稿批准门的服务端推送形态。"""
    session: str
    draft_id: str
    prompt: str



class LlmSettings(BaseModel):
    provider: str = "deepseek"
    model: str
    base_url: str
    api_key_spec: Dict[str, str] = Field(default_factory=dict)
    temperature: float = 0.0
    max_tokens: Optional[int] = None


class SettingsView(BaseModel):
    """redacted 设置视图：env-owned 路径带 _source 标注。"""
    version: int
    settings: Dict[str, Any]
    env_owned: List[str]


class UsageSummary(BaseModel):
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

NOTIFICATION_METHODS = {
    "run.step": RunStepNotification,
    "run.outcome": RunOutcomeNotification,
    "approval.elicit": ApprovalElicitation,
}
