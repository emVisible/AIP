"""The five benchmark implementations (SPEC App. E).

A. Traditional long-context agent   — every decision re-sends the growing transcript
B. MCP agent                        — tool schemas + growing observation log in context
C. AIP + Context-on-Demand          — per-decision minimal event/state, fetch-on-demand
D. C + small model                  — simple decisions routed to a cheap model
E. C + rule + small + LLM cascade   — deterministic steps cost zero tokens

All five produce the same scripted decisions (equalized success), so the
numbers compare context efficiency and cost per successful task.
"""
from typing import List, Tuple

from .models import CONTEXT, est_tokens, usd
from .task import STEPS, LLM, RULES, SMALL


class Agent:
    name = "?"

    def __init__(self) -> None:
        self.calls_log: List[Tuple[int, int, str]] = []  # (in, out, tier)

    # --- accounting -----------------------------------------------------------
    def record(self, tokens_in: int, tokens_out: int, tier: str) -> None:
        if tier != "none":
            self.calls_log.append((tokens_in, tokens_out, tier))

    @property
    def calls(self) -> int:
        return len(self.calls_log)

    @property
    def total_in(self) -> int:
        return sum(c[0] for c in self.calls_log)

    @property
    def total_out(self) -> int:
        return sum(c[1] for c in self.calls_log)

    @property
    def total_tokens(self) -> int:
        return self.total_in + self.total_out

    @property
    def avg_context(self) -> float:
        return sum(c[0] for c in self.calls_log) / max(1, self.calls)

    @property
    def cost(self) -> float:
        return sum(usd(ti, to, tier) for ti, to, tier in self.calls_log)

    @property
    def tier_calls(self) -> dict:
        out = {"llm": 0, "small": 0}
        for _, _, tier in self.calls_log:
            if tier in out:
                out[tier] += 1
        return out

    # --- model -----------------------------------------------------------------
    def decide(self, step: dict) -> Tuple[int, int, str]:
        raise NotImplementedError

    def run(self, steps=None) -> "Agent":
        for step in steps or STEPS:
            self.record(*self.decide(step))
        return self


class LongContextAgent(Agent):
    name = "A: traditional long-context agent"
    SYSTEM = CONTEXT["A"]["system"]
    PAGE = CONTEXT["A"]["page"]
    OUT = CONTEXT["A"]["out"]

    def __init__(self) -> None:
        super().__init__()
        self.transcript: List[str] = []

    def decide(self, step: dict) -> Tuple[int, int, str]:
        observation = f"{step['event']} {step['data']}"
        self.transcript.append(observation)
        ctx = self.SYSTEM + self.PAGE + est_tokens(self.transcript)
        self.transcript.append(f"action: {step['decision']}")
        return ctx, self.OUT, "llm"


class McpAgent(Agent):
    name = "B: MCP agent"
    SYSTEM = CONTEXT["B"]["system"]
    TOOLS = CONTEXT["B"]["tools"]
    PAGE = CONTEXT["B"]["page"]
    OUT = CONTEXT["B"]["out"]

    def __init__(self) -> None:
        super().__init__()
        self.log: List[str] = []

    def decide(self, step: dict) -> Tuple[int, int, str]:
        self.log.append(f"{step['event']} {step['data']}")
        ctx = self.SYSTEM + self.TOOLS + self.PAGE + est_tokens(self.log)
        return ctx, self.OUT, "llm"


class AipAgent(Agent):
    name = "C: AIP + Context-on-Demand"
    OVERHEAD = CONTEXT["C"]["event_overhead"]
    OUT = CONTEXT["C"]["out"]

    def decide(self, step: dict) -> Tuple[int, int, str]:
        # Only the fields the decision needs are fetched (context.get);
        # the event packet itself stays minimal.
        data = step["data"]
        if isinstance(data, dict) and "fields" in data:
            data = {f: data.get(f) for f in data["fields"]}
        return self.OVERHEAD + est_tokens(data), self.OUT, "llm"


class CascadeSmallAgent(AipAgent):
    name = "D: AIP + small model"

    def decide(self, step: dict) -> Tuple[int, int, str]:
        tokens_in, tokens_out, _ = super().decide(step)
        tier = "llm" if step["decision"] in LLM else "small"
        return tokens_in, tokens_out, tier


class CascadeRuleAgent(AipAgent):
    name = "E: AIP + rule + small + LLM cascade"

    def decide(self, step: dict) -> Tuple[int, int, str]:
        decision = step["decision"]
        if decision in RULES:
            return 0, 0, "none"  # deterministic — zero model cost
        tokens_in, tokens_out, _ = super().decide(step)
        tier = "llm" if decision in LLM else "small"
        return tokens_in, tokens_out, tier


ALL_MODELS = [LongContextAgent, McpAgent, AipAgent, CascadeSmallAgent, CascadeRuleAgent]