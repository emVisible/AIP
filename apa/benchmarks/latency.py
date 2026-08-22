"""APA 延迟基准（设计文档 §14.4 executor_latency）。

度量内嵌回路的动作往返延迟（send → terminal ok）：
    EmbeddedGateway + RecordingExecutor + MockPage

    python -m benchmarks.latency [--n 200]

输出 p50/p95/p99 与吞吐。CI 冒烟：n=50 时断言 p95 < 500ms（防回归）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

APA_ROOT = Path(__file__).resolve().parent.parent
for p in ("apa-core", "apa-sdk-python", "apa-executors"):
    sys.path.insert(0, str(APA_ROOT / "packages" / p))
sys.path.insert(0, str(APA_ROOT / ".." / "sdk" / "python"))

from aip import AIPPeer  # noqa: E402

from apa_core.embedded import EmbeddedGateway  # noqa: E402
from apa_core.policy import PolicyConfig  # noqa: E402
from apa_core.registry import load_registries  # noqa: E402


class EchoExecutor:
    """最小执行器：接受任意动作并立即 ok。"""

    def __init__(self, source: str, session_id: str) -> None:
        from aip import AIPPeer as _P
        self.peer = _P(source=source, session_id=session_id)
        self.executed = 0

    def on_message(self, raw: dict) -> None:
        cls, msg = self.peer.handle(raw)
        if cls != "accept" or msg.type != "action":
            return
        self.executed += 1
        self.peer.send_result("ok", in_reply_to=msg.id,
                              data={"echo": msg.payload.get("name")})


def run(n_actions: int = 200, *, session: str = "s_bench") -> dict:
    registries = load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml")
    gateway = EmbeddedGateway(
        session, registry=registries, policy=PolicyConfig(),
        identities={"executor": f"ex_{session}", "agent": f"ag_{session}"})

    executor = EchoExecutor(f"ex_{session}", session)
    agent_peer = AIPPeer(source=f"ag_{session}", session_id=session)

    current = {"id": None, "t1": None}

    class AgentInbox:
        def on_message(self, raw: dict) -> None:
            cls, msg = agent_peer.handle(raw)
            if cls != "accept" or msg.type != "result":
                return
            if msg.in_reply_to == current["id"] \
                    and msg.payload.get("status") == "ok":
                current["t1"] = time.perf_counter()

    gateway.attach_executor(executor, f"ex_{session}")
    inbox = AgentInbox()
    inbox.peer = agent_peer
    gateway.attach_agent(inbox, f"ag_{session}")
    gateway.run()

    latencies: list = []
    for i in range(n_actions):
        current["id"] = None
        current["t1"] = None
        act = agent_peer.build_action(
            "browser.scroll",
            params={"direction": "down" if i % 2 else "up"},
        )
        current["id"] = act.id
        t0 = time.perf_counter()
        agent_peer.send(act)   # 同步传输：terminal ok 在 send 内重入完成（DE-1）
        t1 = current.get("t1") or time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    latencies.sort()

    def pct(p: float) -> float:
        idx = min(len(latencies) - 1, int(round(p / 100 * (len(latencies) - 1))))
        return round(latencies[idx], 3)

    return {
        "n": len(latencies),
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "min_ms": round(latencies[0], 3),
        "max_ms": round(latencies[-1], 3),
        "actions_per_sec": round(len(latencies) / (sum(latencies) / 1000), 1)
        if latencies else 0.0,
        "executed": executor.executed,
    }


def main() -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(prog="latency",
                                     description="APA 动作往返延迟基准")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--json", default=None, help="结果写入 JSON 文件")
    args = parser.parse_args()
    data = run(n_actions=args.n)
    print(json.dumps(data, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())