"""apa-core: EmbeddedGateway（设计文档 §13.2 模式 C）。

在应用进程内嵌入 Gateway 与对端（executor / decision engine）直连。
AIP §2 明确支持 peer-to-peer；嵌入式模式适合开发与轻量部署，
生产环境使用独立 Gateway + WebSocket（见 sdk/python/aip/ws.py）。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from aip import AIPPeer

from .gateway import APAGateway


class EmbeddedGateway:
    """把 executor 与 decision engine 通过网关串起来的最小装配。

    用法（§14.2 hello-rpa）：
        gw = EmbeddedGateway(
            session_id="s_hello_001",
            registry=registry, policy=policy,
            identities={"executor": "browser_01", "agent": "rule_agent_001"},
        )
        executor = BrowserExecutor(...)  # 实现 on_message + peer
        agent = RuleBasedAgent(...)      # 实现 on_message + peer
        gw.attach_executor(executor, source="browser_01")
        gw.attach_agent(agent, source="rule_agent_001")
        gw.run()
    """

    def __init__(
        self,
        session_id: str,
        *,
        registry=None,
        policy=None,
        identities: Optional[Dict[str, str]] = None,
        audit=None,
        clock=None,
        process_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self.gateway = APAGateway(
            session_id,
            registry=registry,
            policy=policy,
            identities=identities,
            audit=audit,
            clock=clock,
            process_id=process_id,
            tenant_id=tenant_id,
        )

    def attach_executor(self, executor, source: str) -> AIPPeer:
        executor.peer.source = source
        executor.peer.transport = _ToGateway("executor", self.gateway)
        self.gateway.set_handler("executor", executor.on_message)
        self.gateway.sm.executor_ready(source)
        return executor.peer

    def attach_agent(self, agent, source: str) -> AIPPeer:
        agent.peer.source = source
        agent.peer.transport = _ToGateway("agent", self.gateway)
        self.gateway.set_handler("agent", agent.on_message)
        return agent.peer

    def run(self) -> None:
        """将网关连接状态置为运行，启动 Session。"""
        self.gateway.sm.start()
        self.gateway.connected["executor"] = True
        self.gateway.connected["agent"] = True

    def tick(self) -> None:
        self.gateway.tick()

    def summary(self) -> dict:
        return self.gateway.summary()


class _ToGateway:
    """把 peer.send() 的消息直接交给网关的 deliver()。"""

    def __init__(self, side: str, gateway: APAGateway) -> None:
        self.side = side
        self.gateway = gateway

    def send(self, message: dict) -> None:
        self.gateway.deliver(self.side, message)