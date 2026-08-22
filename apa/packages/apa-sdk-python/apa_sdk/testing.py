"""apa-sdk: 测试工具（设计文档 §14.3 Step 4 / §14.4 测试策略）。

· MockGateway：EmbeddedGateway + 注入 action/事件 的便捷入口
· EventRecorder：记录流经 gateway 的消息
· MockBrowser / MockPage：浏览器 DOM 模型（供 BrowserExecutor 测试）
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from aip import AIPPeer

from apa_core.embedded import EmbeddedGateway
from apa_core.gateway import APAGateway

from .executor_base import AIPExecutor
from .semantic_adapter import Element, ScreenState


class EventRecorder:
    """记录所有流经 gateway 的消息，便于断言。"""

    def __init__(self) -> None:
        self.events: List[dict] = []
        self.actions: List[dict] = []
        self.results: List[dict] = []
        self.errors: List[dict] = []

    def __call__(self, raw: dict) -> None:
        kind = raw.get("type")
        bucket = {
            "event": self.events, "action": self.actions,
            "result": self.results, "error": self.errors,
        }.get(kind)
        if bucket is not None:
            bucket.append(raw)

    def last_result(self) -> Optional[dict]:
        return self.results[-1] if self.results else None

    def result_statuses(self) -> List[str]:
        return [r.get("payload", {}).get("status") for r in self.results]

    def event_names(self) -> List[str]:
        return [e.get("payload", {}).get("name") for e in self.events]


class MockGateway(EmbeddedGateway):
    """内嵌网关 + 注入助手。用途：不启动真实浏览器/Agent 即可驱动测试。"""

    def attach(self, executor: AIPExecutor, source: str, agent, agent_source: str,
               recorder: Optional[EventRecorder] = None) -> None:
        if recorder is None:
            recorder = EventRecorder()
        self.recorder = recorder
        old_exec = self.gateway.handlers.get("executor")
        self.gateway.set_handler("executor",
                                 _wrap(old_exec, recorder))
        old_agent = self.gateway.handlers.get("agent")
        self.gateway.set_handler("agent", _wrap(old_agent, recorder))
        self.attach_executor(executor, source)
        self.attach_agent(agent, agent_source)
        self.run()

    def inject_action(self, name: str, params: Optional[dict] = None, *,
                      source: str = "agent_001", action_id: Optional[str] = None,
                      target: Optional[str] = None) -> dict:
        """模拟 Decision Engine 发送一个 action。返回原始 action 消息。"""
        msg = make_action_like(
            session=self.gateway.session_id, source=source, name=name,
            params=params, target=target, id=action_id,
        )
        self.gateway.deliver("agent", msg)
        return msg

    def inject_event(self, name: str, data: Optional[dict] = None, *,
                     source: str = "executor_001", id: Optional[str] = None) -> dict:
        msg = make_event_like(
            session=self.gateway.session_id, source=source, name=name, data=data, id=id)
        self.gateway.deliver("executor", msg)
        return msg


def make_action_like(session: str, source: str, name: str, *,
                     params: Optional[dict] = None, target: Optional[str] = None,
                     id: Optional[str] = None) -> dict:
    from aip import make_action
    msg = make_action(session, source, name, target=target, params=params, id=id)
    msg.seq = 0  # 由 peer 的 Sequencer 分配
    return msg.to_dict()


def make_event_like(session: str, source: str, name: str, *,
                    data: Optional[dict] = None, id: Optional[str] = None) -> dict:
    from aip import make_event
    msg = make_event(session, source, name, data=data, id=id)
    msg.seq = 0
    return msg.to_dict()


def wrap_handlers(gateway: APAGateway, recorder: EventRecorder) -> None:
    """把 gateway 的 handlers 包装为同时写入 recorder。"""
    for side in ("executor", "agent"):
        old = gateway.handlers.get(side)
        if old is not None:
            gateway.set_handler(side, _wrap(old, recorder))


def _wrap(handler: Callable[[dict], None], recorder: EventRecorder) -> Callable[[dict], None]:
    def wrapped(raw: dict) -> None:
        recorder(raw)
        handler(raw)
    return wrapped


# --- 浏览器模拟 ------------------------------------------------------------------
class MockElement:
    def __init__(self, *, role: str = "", text: str = "", id: str = "",
                 data_apa_id: str = "", attrs: Optional[dict] = None) -> None:
        self.role = role
        self.text = text
        self.id = id
        self.data_apa_id = data_apa_id
        self.attrs = attrs or {}
        self.value = ""

    def to_element(self) -> Element:
        return Element(
            role=self.role, text=self.text, id=self.id,
            data_apa_id=self.data_apa_id, attrs=dict(self.attrs),
        )


class MockLocator:
    def __init__(self, page: "MockPage", target: str) -> None:
        self.page = page
        self.target = target

    def click(self, **kw) -> None:
        el = self.page._find(self.target)
        if el is None:
            raise ValueError(f"element {self.target!r} not found")
        self.page.clicked.append(self.target)

    def fill(self, value: str, **kw) -> None:
        el = self.page._find(self.target)
        if el is None:
            raise ValueError(f"element {self.target!r} not found")
        el.value = value

    def inner_text(self) -> str:
        el = self.page._find(self.target)
        return el.text if el else ""

    def count(self) -> int:
        return 1 if self.page._find(self.target) else 0


class MockPage:
    """极简 DOM 模型，模拟 BrowserExecutor 用到的 Playwright 子集。"""

    def __init__(self) -> None:
        self.url = ""
        self.title = ""
        self.elements: List[MockElement] = []
        self.clicked: List[str] = []
        self.loads = 0

    def goto(self, url: str, wait_until: str = "networkidle") -> None:
        self.url = url
        self.loads += 1

    def inner_text(self, target: str) -> str:
        return self.locator(target).inner_text()

    def click(self, target: str, force: bool = False) -> None:
        self.locator(target).click(force=force)

    def fill(self, target: str, value: str, clear_first: bool = True) -> None:
        self.locator(target).fill(value, clear_first=clear_first)

    def locator(self, target: str) -> MockLocator:
        return MockLocator(self, target)

    def _find(self, target: str):
        if target.startswith("#") or target.startswith("."):
            attr = target[0]
            want = target[1:]
            for e in self.elements:
                if attr == "#" and e.id == want:
                    return e
                if attr == "." and want in e.attrs.get("class", "").split():
                    return e
        if target.startswith("[") and target.endswith("]"):
            inner = target[1:-1]
            attr, _, val = inner.partition("=")
            val = val.strip("'\"")
            for e in self.elements:
                if attr == "data-apa-id" and e.data_apa_id == val:
                    return e
                if e.attrs.get(attr) == val:
                    return e
        for e in self.elements:
            if e.data_apa_id == target or e.id == target or e.text == target:
                return e
        return None

    def screen_state(self) -> ScreenState:
        return ScreenState(
            url=self.url, title=self.title,
            elements=[e.to_element() for e in self.elements],
        )